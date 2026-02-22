/**
 * Nova — P2P Client with Google OAuth.
 * Optimized for low-bandwidth / unstable connections.
 *
 * Resilience features:
 *   - Socket.IO auto-reconnect with backoff
 *   - WebRTC ICE restart on connection failure
 *   - Message queue during temporary disconnects
 *   - Polling fallback when WebSocket fails
 *   - Connection status indicators
 *   - Ordered + reliable DataChannel
 */
(()=>{
"use strict";

const $=id=>document.getElementById(id);
const GCID = window.__GOOGLE_CLIENT_ID__ || "";

// ── Screens ─────────────────────────────────────────────────────────────────
const A=$("A"), L=$("L"), C=$("C");
const ml=$("ml"),mi=$("mi"),se=$("se"),sd=$("sd"),st=$("st"),
      ti=$("ti"),ol=$("ol"),oc=$("oc"),uname=$("uname"),uavatar=$("uavatar");

let currentUser = null;
let io_ = null;
let pc = null;
let dc = null;
let matched = false;
let wt = null, wasT = false;
let iceRestarts = 0;
const MAX_ICE_RESTARTS = 3;
const msgQueue = [];       // queue messages while DC is temporarily closed
let peerInitiator = false; // track if we initiated the peer connection

function show(el){document.querySelectorAll(".s").forEach(s=>s.classList.remove("on"));el.classList.add("on")}
function clear(){ml.innerHTML="";msgQueue.length=0}
function scroll(){requestAnimationFrame(()=>{ml.scrollTop=ml.scrollHeight})}
function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML}

function add(txt,type){
  const d=document.createElement("div");
  if(type==="s"){d.className="sm";d.innerHTML="<span>"+txt+"</span>"}
  else{d.className="mg "+(type==="y"?"y":"st");
    d.innerHTML='<span class="lb">'+(type==="y"?"You":"Stranger")+"</span>"+esc(txt)}
  ml.appendChild(d);scroll();
}

// ── UI State ────────────────────────────────────────────────────────────────
function setConn(){
  matched=true;iceRestarts=0;mi.disabled=false;se.disabled=false;mi.focus();
  sd.className="sd c";st.textContent="Connected (P2P)";
  // Flush any queued messages
  flushQueue();
}
function setWait(){
  matched=false;mi.disabled=true;se.disabled=true;mi.value="";
  ti.classList.remove("on");sd.className="sd w";st.textContent="Searching…";
  closePeer();
}
function setDC(){
  matched=false;mi.disabled=true;se.disabled=true;
  ti.classList.remove("on");sd.className="sd";st.textContent="Disconnected";
  closePeer();
}
function setReconnecting(){
  mi.disabled=true;se.disabled=true;
  sd.className="sd w";st.textContent="Reconnecting…";
}
function autoH(){mi.style.height="auto";mi.style.height=Math.min(mi.scrollHeight,100)+"px"}

// ── Auth ────────────────────────────────────────────────────────────────────
async function api(url, body){
  try{
    const r = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    return r.json();
  }catch(e){
    return {ok:false,err:"Network error. Check your connection."};
  }
}

// Check session on load
fetch("/api/me").then(r=>r.json()).then(d=>{
  if(d.ok) enterLobby(d.user);
}).catch(()=>{});

// TOS checkbox
const tosCb=$("tos-cb");

// Google Sign-In (if configured)
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
  closePeer();
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

// ── Socket.IO (with reconnection for low internet) ──────────────────────────
function connectSocket(){
  if(io_) return;
  io_=io({
    transports:["websocket","polling"],   // fallback to polling on bad connections
    reconnection:true,
    reconnectionAttempts:Infinity,         // never give up
    reconnectionDelay:1000,               // start at 1s
    reconnectionDelayMax:10000,           // max 10s between retries
    timeout:30000,                        // 30s connection timeout (slow networks)
    forceNew:false,
  });

  // Connection status
  io_.on("connect",()=>{
    console.log("Socket connected");
  });
  io_.on("disconnect",reason=>{
    console.log("Socket disconnected:",reason);
    if(matched){
      setReconnecting();
      add("⚠ Connection unstable, reconnecting…","s");
    }
  });
  io_.on("reconnect",attempt=>{
    console.log("Socket reconnected after",attempt,"attempts");
    if(matched) add("✓ Reconnected to server","s");
  });
  io_.on("reconnect_attempt",attempt=>{
    if(attempt%5===0) add("⚠ Trying to reconnect… (attempt "+attempt+")","s");
  });

  io_.on("oc",n=>{ol.textContent=n;oc.textContent=n});
  io_.on("w",()=>{setWait()});

  io_.on("m",data=>{
    add("Matched! Establishing P2P connection…","s");
    peerInitiator=data.init;
    setupPeer(data.init);
  });

  // WebRTC signaling
  io_.on("offer",async data=>{
    if(!pc)return;
    try{
      await pc.setRemoteDescription(data);
      const ans=await pc.createAnswer();
      await pc.setLocalDescription(ans);
      io_.emit("answer",pc.localDescription.toJSON());
    }catch(e){console.warn("Offer handling error:",e)}
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
    setDC();add("Stranger has disconnected.","s");showFindNew();
  });
}

// ── WebRTC P2P (optimized for low bandwidth) ────────────────────────────────
const RTC_CONFIG={
  iceServers:[
    {urls:"stun:stun.l.google.com:19302"},
    {urls:"stun:stun1.l.google.com:19302"},
    {urls:"turn:openrelay.metered.ca:80",username:"openrelayproject",credential:"openrelayproject"},
    {urls:"turn:openrelay.metered.ca:443",username:"openrelayproject",credential:"openrelayproject"},
    {urls:"turn:openrelay.metered.ca:443?transport=tcp",username:"openrelayproject",credential:"openrelayproject"},
  ],
  iceCandidatePoolSize:5,        // pre-gather candidates for faster connection
  iceTransportPolicy:"all",      // try all (direct + relay)
};

function closePeer(){
  if(dc){try{dc.close()}catch(_){} dc=null}
  if(pc){try{pc.close()}catch(_){} pc=null}
  iceRestarts=0;
}

function setupPeer(isInit){
  closePeer();
  pc=new RTCPeerConnection(RTC_CONFIG);

  pc.onicecandidate=e=>{
    if(e.candidate&&io_) io_.emit("ice",e.candidate.toJSON());
  };

  // ICE connection monitoring with restart logic
  pc.oniceconnectionstatechange=()=>{
    if(!pc) return;
    const s=pc.iceConnectionState;
    console.log("ICE state:",s);

    if(s==="disconnected"){
      // Temporary disconnect — wait a bit, then try ICE restart
      st.textContent="Connection unstable…";
      sd.className="sd w";
      setTimeout(()=>{
        if(pc&&pc.iceConnectionState==="disconnected"&&iceRestarts<MAX_ICE_RESTARTS){
          iceRestarts++;
          add("⚠ Reconnecting to peer… (attempt "+iceRestarts+")","s");
          tryIceRestart();
        }
      },3000);
    } else if(s==="failed"){
      if(iceRestarts<MAX_ICE_RESTARTS){
        iceRestarts++;
        add("⚠ Connection failed, retrying… (attempt "+iceRestarts+")","s");
        tryIceRestart();
      } else {
        setDC();add("P2P connection lost after "+MAX_ICE_RESTARTS+" retries.","s");showFindNew();
      }
    } else if(s==="connected"||s==="completed"){
      sd.className="sd c";
      st.textContent="Connected (P2P)";
      if(iceRestarts>0) add("✓ Reconnected to peer!","s");
    }
  };

  pc.onconnectionstatechange=()=>{
    if(!pc) return;
    if(pc.connectionState==="failed"&&iceRestarts>=MAX_ICE_RESTARTS){
      setDC();add("P2P connection lost.","s");showFindNew();
    }
  };

  if(isInit){
    // Ordered + reliable DataChannel for text (works better on bad connections)
    dc=pc.createDataChannel("chat",{ordered:true});
    bindDC(dc);
    pc.createOffer().then(o=>pc.setLocalDescription(o))
      .then(()=>io_.emit("offer",pc.localDescription.toJSON()))
      .catch(e=>console.warn("Offer creation error:",e));
  }else{
    pc.ondatachannel=e=>{dc=e.channel;bindDC(dc)};
  }
}

function tryIceRestart(){
  if(!pc||!io_) return;
  try{
    if(peerInitiator){
      pc.createOffer({iceRestart:true}).then(o=>pc.setLocalDescription(o))
        .then(()=>io_.emit("offer",pc.localDescription.toJSON()))
        .catch(e=>console.warn("ICE restart error:",e));
    }
    // Non-initiator waits for the new offer
  }catch(e){console.warn("ICE restart failed:",e)}
}

function bindDC(ch){
  ch.onopen=()=>{setConn();add("Connected peer-to-peer! Say hi!","s")};
  ch.onclose=()=>{
    if(matched&&iceRestarts>=MAX_ICE_RESTARTS){
      setDC();add("Stranger has disconnected.","s");showFindNew();
    }
    // If iceRestarts < max, the ICE restart logic will handle reconnection
  };
  ch.onmessage=e=>{
    try{
      const d=JSON.parse(e.data);
      if(d.t!==undefined){
        if(d.t){ti.classList.add("on");scroll()}else ti.classList.remove("on");
      }else if(d.m){add(d.m,"st");ti.classList.remove("on")}
    }catch(_){}
  };
}

// ── P2P messaging with queue ────────────────────────────────────────────────
function dcSend(obj){
  if(dc&&dc.readyState==="open"){
    dc.send(JSON.stringify(obj));
  } else if(matched){
    // Queue message for when connection recovers
    if(obj.m) msgQueue.push(obj);
  }
}

function flushQueue(){
  while(msgQueue.length>0&&dc&&dc.readyState==="open"){
    dc.send(JSON.stringify(msgQueue.shift()));
  }
}

function typing(){
  if(!matched)return;
  if(!wasT){wasT=true;dcSend({t:1})}
  clearTimeout(wt);
  wt=setTimeout(()=>{wasT=false;dcSend({t:0})},1200);
}

function send(){
  const t=mi.value.trim();if(!t||!matched)return;
  dcSend({m:t});add(t,"y");mi.value="";autoH();
  clearTimeout(wt);if(wasT){wasT=false;dcSend({t:0})}
}

function showFindNew(){
  const b=document.createElement("div");b.className="sm";
  b.innerHTML='<button class="b bf" id="fn">Find New Stranger</button>';
  ml.appendChild(b);scroll();
  $("fn").onclick=()=>{clear();setWait();add("Looking for a new stranger…","s");io_.emit("q")};
}

// ── UI Events ───────────────────────────────────────────────────────────────
$("go").onclick=()=>{show(C);clear();setWait();add("Looking for a stranger…","s");io_.emit("q")};
se.onclick=send;
mi.onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send()}};
mi.oninput=()=>{autoH();typing()};
$("sk").onclick=()=>{clear();setWait();add("Looking for a new stranger…","s");io_.emit("s")};
$("dc").onclick=()=>{io_.emit("s");setDC();clear();show(L)};

})();
