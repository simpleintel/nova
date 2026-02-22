/**
 * Nova — P2P Video Chat (Omegle-style).
 * Video-only, no text. Google OAuth.
 * Resilient for low-bandwidth connections & mobile.
 */
(()=>{
"use strict";

const $=id=>document.getElementById(id);
const GCID = window.__GOOGLE_CLIENT_ID__ || "";

// ── Screens ─────────────────────────────────────────────────────────────────
const A=$("A"), L=$("L"), C=$("C");
const rv=$("rv"),lv=$("lv"),vs=$("vs"),vsText=$("vs-text"),vsSub=$("vs-sub");
const ol=$("ol"),oc=$("oc"),uname=$("uname"),uavatar=$("uavatar");

let currentUser = null;
let io_ = null;
let pc = null;
let localStream = null;
let matched = false;
let iceRestarts = 0;
let peerInitiator = false;
let camOn = true, micOn = true;
const MAX_ICE_RESTARTS = 3;

function show(el){document.querySelectorAll(".s").forEach(s=>s.classList.remove("on"));el.classList.add("on")}

// ── Camera ──────────────────────────────────────────────────────────────────
async function getCamera(){
  if(localStream){
    // Check tracks are still alive
    const alive = localStream.getTracks().some(t=>t.readyState==="live");
    if(alive) return localStream;
    // Tracks ended — re-acquire
    localStream = null;
  }

  // Try progressively simpler constraints for maximum compatibility
  const attempts = [
    {video:{width:{ideal:640},height:{ideal:480},facingMode:"user"}, audio:true},
    {video:{facingMode:"user"}, audio:true},
    {video:true, audio:true},
    {video:true, audio:false},  // some devices block mic separately
  ];

  for(const constraints of attempts){
    try{
      localStream = await navigator.mediaDevices.getUserMedia(constraints);
      lv.srcObject = localStream;
      lv.play().catch(()=>{});
      console.log("Camera acquired with:", JSON.stringify(constraints));
      return localStream;
    }catch(e){
      console.warn("getUserMedia failed with:", JSON.stringify(constraints), e.name, e.message);
      continue;
    }
  }

  // All attempts failed
  console.error("All camera attempts failed");
  return null;
}

function stopCamera(){
  if(localStream){
    localStream.getTracks().forEach(t=>t.stop());
    localStream=null;
    lv.srcObject=null;
  }
}

// ── Status UI ───────────────────────────────────────────────────────────────
function showStatus(text,sub,showRetry){
  vs.style.display="block";
  vsText.textContent=text;
  vsSub.textContent=sub||"";
  // Show/hide retry button
  let rb=$("retry-btn");
  if(showRetry){
    if(!rb){
      rb=document.createElement("button");
      rb.id="retry-btn";
      rb.textContent="🔄 Retry Camera";
      rb.style.cssText="margin-top:14px;padding:10px 24px;border:none;border-radius:10px;background:#4a3fc0;color:#fff;font:inherit;font-size:15px;font-weight:600;cursor:pointer";
      rb.onclick=retryCamera;
      vs.appendChild(rb);
    }
    rb.style.display="inline-block";
  } else if(rb){
    rb.style.display="none";
  }
}
function hideStatus(){
  vs.style.display="none";
  let rb=$("retry-btn");
  if(rb) rb.style.display="none";
}

async function retryCamera(){
  showStatus("Retrying camera…","");
  localStream=null; // force re-acquire
  const stream = await getCamera();
  if(stream){
    showStatus("Looking for someone…","Hang tight");
    io_.emit("q");
  } else {
    showStatus("Camera access required",
      navigator.userAgent.match(/iPhone|iPad/i)
        ? "Go to Settings → Safari → Camera & Microphone → Allow"
        : "Tap the 🔒 icon in your browser's address bar → Allow Camera & Mic",
      true);
  }
}

function setWait(){
  matched=false;iceRestarts=0;
  rv.srcObject=null;
  showStatus("Looking for someone…","Hang tight");
  closePeer();
}
function setConnected(){
  matched=true;iceRestarts=0;
  hideStatus();
}
function setDC(){
  matched=false;
  rv.srcObject=null;
  closePeer();
}

// ── Auth ────────────────────────────────────────────────────────────────────
async function api(url, body){
  try{
    const r = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    return r.json();
  }catch(e){
    return {ok:false,err:"Network error. Check your connection."};
  }
}

fetch("/api/me").then(r=>r.json()).then(d=>{
  if(d.ok) enterLobby(d.user);
}).catch(()=>{});

const tosCb=$("tos-cb");

if(GCID){
  window.addEventListener("load",()=>{
    if(typeof google==="undefined"||!google.accounts) return;
    google.accounts.id.initialize({
      client_id: GCID,
      callback: async resp=>{
        $("a-err").textContent="";
        if(!tosCb.checked){
          $("a-err").textContent="You must accept the Terms of Service.";
          return;
        }
        const d = await api("/api/auth/google",{credential:resp.credential,tos_accepted:true});
        if(d.ok) enterLobby(d.user);
        else $("a-err").textContent=d.err||"Google login failed";
      },
    });
    google.accounts.id.renderButton($("g-btn"),{
      theme:"outline", size:"large", width:280, text:"signin_with",
    });
  });
}

$("logout").onclick=async()=>{
  await fetch("/api/logout",{method:"POST"}).catch(()=>{});
  currentUser=null;
  if(io_){io_.disconnect();io_=null}
  stopCamera();closePeer();
  show(A);
};

function enterLobby(user){
  currentUser=user;
  uname.textContent=user.name||user.email;
  if(user.avatar){uavatar.src=user.avatar;uavatar.style.display="inline"}
  else{uavatar.style.display="none"}
  show(L);
  connectSocket();
}

// ── Socket.IO ───────────────────────────────────────────────────────────────
function connectSocket(){
  if(io_) return;
  io_=io({
    transports:["websocket","polling"],
    reconnection:true,
    reconnectionAttempts:Infinity,
    reconnectionDelay:1000,
    reconnectionDelayMax:10000,
    timeout:30000,
  });

  io_.on("connect",()=>console.log("Socket connected"));
  io_.on("disconnect",reason=>{
    console.log("Socket disconnected:",reason);
    if(matched) showStatus("Reconnecting…","Connection unstable");
  });
  io_.on("reconnect",()=>{
    if(matched) hideStatus();
  });

  io_.on("oc",n=>{ol.textContent=n;oc.textContent=n});
  io_.on("w",()=>{setWait()});

  io_.on("m",async data=>{
    showStatus("Matched! Connecting video…","Establishing peer-to-peer link");
    peerInitiator=data.init;
    setupPeer(data.init);
  });

  io_.on("offer",async data=>{
    if(!pc)return;
    try{
      await pc.setRemoteDescription(data);
      const ans=await pc.createAnswer();
      await pc.setLocalDescription(ans);
      io_.emit("answer",pc.localDescription.toJSON());
    }catch(e){console.warn("Offer error:",e)}
  });
  io_.on("answer",async data=>{
    if(!pc)return;
    try{await pc.setRemoteDescription(data)}catch(e){console.warn("Answer error:",e)}
  });
  io_.on("ice",async data=>{
    if(!pc)return;
    try{await pc.addIceCandidate(data)}catch(_){}
  });

  io_.on("pd",()=>{
    setDC();
    showStatus("Stranger left","Click Next to find someone new");
  });
}

// ── WebRTC ──────────────────────────────────────────────────────────────────
const RTC_CONFIG={
  iceServers:[
    {urls:"stun:stun.l.google.com:19302"},
    {urls:"stun:stun1.l.google.com:19302"},
    {urls:"turn:openrelay.metered.ca:80",username:"openrelayproject",credential:"openrelayproject"},
    {urls:"turn:openrelay.metered.ca:443",username:"openrelayproject",credential:"openrelayproject"},
    {urls:"turn:openrelay.metered.ca:443?transport=tcp",username:"openrelayproject",credential:"openrelayproject"},
  ],
  iceCandidatePoolSize:5,
};

function closePeer(){
  if(pc){try{pc.close()}catch(_){} pc=null}
  iceRestarts=0;
}

async function setupPeer(isInit){
  closePeer();

  // Make sure we have camera
  const stream = await getCamera();
  if(!stream){
    showStatus("Camera access required",
      navigator.userAgent.match(/iPhone|iPad/i)
        ? "Go to Settings → Safari → Camera & Microphone → Allow"
        : "Tap the 🔒 icon in your browser's address bar → Allow Camera & Mic",
      true);
    return;
  }

  pc=new RTCPeerConnection(RTC_CONFIG);

  // Add local video/audio tracks to the connection
  stream.getTracks().forEach(t=>pc.addTrack(t,stream));

  // Receive remote video
  pc.ontrack=e=>{
    if(e.streams&&e.streams[0]){
      rv.srcObject=e.streams[0];
      // Ensure playback starts (mobile autoplay policy)
      rv.play().catch(()=>{});
      setConnected();
    }
  };

  pc.onicecandidate=e=>{
    if(e.candidate&&io_) io_.emit("ice",e.candidate.toJSON());
  };

  pc.oniceconnectionstatechange=()=>{
    if(!pc) return;
    const s=pc.iceConnectionState;
    console.log("ICE:",s);

    if(s==="disconnected"){
      showStatus("Connection unstable…","Trying to reconnect");
      setTimeout(()=>{
        if(pc&&pc.iceConnectionState==="disconnected"&&iceRestarts<MAX_ICE_RESTARTS){
          iceRestarts++;
          tryIceRestart();
        }
      },3000);
    } else if(s==="failed"){
      if(iceRestarts<MAX_ICE_RESTARTS){
        iceRestarts++;
        showStatus("Reconnecting… ("+iceRestarts+"/"+MAX_ICE_RESTARTS+")","");
        tryIceRestart();
      } else {
        setDC();
        showStatus("Connection lost","Click Next to find someone new");
      }
    } else if(s==="connected"||s==="completed"){
      setConnected();
    }
  };

  pc.onconnectionstatechange=()=>{
    if(!pc) return;
    if(pc.connectionState==="failed"&&iceRestarts>=MAX_ICE_RESTARTS){
      setDC();
      showStatus("Connection lost","Click Next to find someone new");
    }
  };

  if(isInit){
    try{
      const offer=await pc.createOffer();
      await pc.setLocalDescription(offer);
      io_.emit("offer",pc.localDescription.toJSON());
    }catch(e){console.warn("Offer error:",e)}
  }
}

function tryIceRestart(){
  if(!pc||!io_) return;
  if(peerInitiator){
    pc.createOffer({iceRestart:true}).then(o=>pc.setLocalDescription(o))
      .then(()=>io_.emit("offer",pc.localDescription.toJSON()))
      .catch(e=>console.warn("ICE restart error:",e));
  }
}

// ── Controls ────────────────────────────────────────────────────────────────
const camBtn=$("cam-tog"), micBtn=$("mic-tog");

camBtn.onclick=()=>{
  if(!localStream) return;
  camOn=!camOn;
  localStream.getVideoTracks().forEach(t=>{t.enabled=camOn});
  camBtn.classList.toggle("off",!camOn);
  camBtn.textContent=camOn?"📷":"🚫";
};

micBtn.onclick=()=>{
  if(!localStream) return;
  micOn=!micOn;
  localStream.getAudioTracks().forEach(t=>{t.enabled=micOn});
  micBtn.classList.toggle("off",!micOn);
  micBtn.textContent=micOn?"🎤":"🔇";
};

// Start chat
$("go").onclick=async()=>{
  show(C);
  showStatus("Starting camera…","Requesting access…");
  const stream = await getCamera();
  if(!stream){
    showStatus("Camera access required",
      navigator.userAgent.match(/iPhone|iPad/i)
        ? "Go to Settings → Safari → Camera & Microphone → Allow"
        : "Tap the 🔒 icon in your browser's address bar → Allow Camera & Mic",
      true);
    return;
  }
  showStatus("Looking for someone…","Hang tight");
  io_.emit("q");
};

// Next
$("sk").onclick=()=>{
  setWait();
  showStatus("Looking for someone…","Hang tight");
  io_.emit("s");
};

// Disconnect — back to lobby
$("dc").onclick=()=>{
  io_.emit("s");
  setDC();
  stopCamera();
  rv.srcObject=null;
  show(L);
};

})();
