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
    const alive = localStream.getTracks().some(t=>t.readyState==="live");
    if(alive) return localStream;
    localStream = null;
  }

  if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia) return null;

  const attempts = [
    {video:{width:{ideal:640},height:{ideal:480},facingMode:"user"},audio:true},
    {video:{facingMode:"user"},audio:true},
    {video:true,audio:true},
    {video:true,audio:false},
  ];

  for(const c of attempts){
    try{
      localStream = await navigator.mediaDevices.getUserMedia(c);
      lv.srcObject = localStream;
      await lv.play().catch(()=>{});
      return localStream;
    }catch(e){
      continue;
    }
  }
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
  localStream=null;
  const stream = await getCamera();
  if(stream){
    showStatus("Looking for someone…","Hang tight");
    io_.emit("q");
  } else {
    const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
    showStatus("Camera access failed",
      isIOS
        ? "iOS: Go to Settings → Safari → Camera & Microphone Access → turn ON for this site. Then reload the page."
        : "Android/Desktop: Tap the lock 🔒 icon in the address bar → Site settings → Allow Camera & Microphone. Then reload.",
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

  io_.on("connect",()=>{});
  io_.on("disconnect",reason=>{
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
    if(!pc) return;
    try{
      await pc.setRemoteDescription(data);
      const ans=await pc.createAnswer();
      await pc.setLocalDescription(ans);
      io_.emit("answer",pc.localDescription.toJSON());
    }catch(e){}
  });
  io_.on("answer",async data=>{
    if(!pc) return;
    try{await pc.setRemoteDescription(data)}catch(e){}
  });
  io_.on("ice",async data=>{
    if(!pc) return;
    try{await pc.addIceCandidate(data)}catch(_){}
  });

  io_.on("pd",()=>{
    setDC();
    showStatus("Stranger left","Finding someone new…");
    setTimeout(()=>{
      if(io_&&io_.connected) io_.emit("q");
    },500);
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

  const stream = await getCamera();
  if(!stream){
    const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
    showStatus("Camera access required",
      isIOS
        ? "iOS: Settings → Safari → Camera → Allow for this site. Reload the page."
        : "Tap 🔒 in address bar → Allow Camera & Mic. Reload.",
      true);
    return;
  }

  pc=new RTCPeerConnection(RTC_CONFIG);

  stream.getTracks().forEach(t=>pc.addTrack(t,stream));

  pc.ontrack=e=>{
    if(e.streams&&e.streams[0]){
      rv.srcObject=e.streams[0];
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
        showStatus("Connection lost","Finding someone new…");
        setTimeout(()=>{ if(io_&&io_.connected) io_.emit("s"); },500);
      }
    } else if(s==="connected"||s==="completed"){
      setConnected();
    }
  };

  pc.onconnectionstatechange=()=>{
    if(!pc) return;
    if(pc.connectionState==="failed"&&iceRestarts>=MAX_ICE_RESTARTS){
      setDC();
      showStatus("Connection lost","Finding someone new…");
      setTimeout(()=>{ if(io_&&io_.connected) io_.emit("s"); },500);
    }
  };

  if(isInit){
    try{
      const offer=await pc.createOffer();
      await pc.setLocalDescription(offer);
      io_.emit("offer",pc.localDescription.toJSON());
    }catch(e){}
  }
}

function tryIceRestart(){
  if(!pc||!io_) return;
  if(peerInitiator){
    pc.createOffer({iceRestart:true}).then(o=>pc.setLocalDescription(o))
      .then(()=>io_.emit("offer",pc.localDescription.toJSON()))
      .catch(()=>{});
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
    const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
    showStatus("Camera access required",
      isIOS
        ? "iOS: Settings → Safari → Camera → Allow. Then reload this page."
        : "Tap 🔒 in address bar → Site settings → Allow Camera & Mic",
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
