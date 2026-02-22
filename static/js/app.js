/**
 * Nova — P2P Client with Google OAuth + email fallback.
 *
 * Security layers:
 *   1. Google OAuth / email login (identity on server)
 *   2. IP + session logged server-side on every action
 *   3. All chat goes over WebRTC DataChannel (P2P, server never sees messages)
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
let isSignup = false;

function show(el){document.querySelectorAll(".s").forEach(s=>s.classList.remove("on"));el.classList.add("on")}
function clear(){ml.innerHTML=""}
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
  matched=true;mi.disabled=false;se.disabled=false;mi.focus();
  sd.className="sd c";st.textContent="Connected (P2P)";
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
function autoH(){mi.style.height="auto";mi.style.height=Math.min(mi.scrollHeight,100)+"px"}

// ── Auth ────────────────────────────────────────────────────────────────────
async function api(url, body){
  const r = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  return r.json();
}

// Check session on load
fetch("/api/me").then(r=>r.json()).then(d=>{
  if(d.ok) enterLobby(d.user);
});

// TOS checkbox
const tosCb=$("tos-cb");

// Google Sign-In (if configured)
if(GCID){
  // Wait for GSI library to load
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

// Email login/signup toggle
const switchEl=$("a-switch");
const loginBtn=$("a-login");
if(switchEl){
  switchEl.onclick=()=>{
    isSignup=!isSignup;
    loginBtn.textContent=isSignup?"Sign Up":"Log In";
    switchEl.textContent=isSignup?"Log in instead":"Sign up";
    $("a-toggle").firstChild.textContent=isSignup?"Have an account? ":"No account? ";
  };
}

loginBtn.onclick=async()=>{
  const email=$("ae").value.trim(), pw=$("ap").value;
  $("a-err").textContent="";
  if(!tosCb.checked){
    $("a-err").textContent="You must accept the Terms of Service.";
    return;
  }
  const d=await api("/api/auth/email",{action:isSignup?"signup":"login",email,password:pw,tos_accepted:true});
  if(d.ok) enterLobby(d.user);
  else $("a-err").textContent=d.err||"Auth failed";
};

$("ap").onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();loginBtn.click()}};
$("ae").onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();$("ap").focus()}};

$("logout").onclick=async()=>{
  await fetch("/api/logout",{method:"POST"});
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

// ── Socket.IO (signaling + matching only) ───────────────────────────────────
function connectSocket(){
  if(io_) return;
  io_=io({transports:["websocket"]});

  io_.on("oc",n=>{ol.textContent=n;oc.textContent=n});
  io_.on("w",()=>{setWait()});

  io_.on("m",data=>{
    add("Matched! Establishing P2P connection…","s");
    setupPeer(data.init);
  });

  // WebRTC signaling
  io_.on("offer",async data=>{
    if(!pc)return;
    await pc.setRemoteDescription(data);
    const ans=await pc.createAnswer();
    await pc.setLocalDescription(ans);
    io_.emit("answer",pc.localDescription.toJSON());
  });
  io_.on("answer",async data=>{
    if(!pc)return;
    await pc.setRemoteDescription(data);
  });
  io_.on("ice",async data=>{
    if(!pc)return;
    try{await pc.addIceCandidate(data)}catch(_){}
  });

  io_.on("pd",()=>{
    setDC();add("Stranger has disconnected.","s");showFindNew();
  });
}

// ── WebRTC P2P ──────────────────────────────────────────────────────────────
const RTC_CONFIG={iceServers:[
  {urls:"stun:stun.l.google.com:19302"},
  {urls:"stun:stun1.l.google.com:19302"},
]};

function closePeer(){
  if(dc){try{dc.close()}catch(_){} dc=null}
  if(pc){try{pc.close()}catch(_){} pc=null}
}

function setupPeer(isInit){
  closePeer();
  pc=new RTCPeerConnection(RTC_CONFIG);

  pc.onicecandidate=e=>{
    if(e.candidate&&io_) io_.emit("ice",e.candidate.toJSON());
  };

  pc.onconnectionstatechange=()=>{
    if(pc&&(pc.connectionState==="failed"||pc.connectionState==="disconnected")){
      setDC();add("P2P connection lost.","s");showFindNew();
    }
  };

  if(isInit){
    dc=pc.createDataChannel("chat");
    bindDC(dc);
    pc.createOffer().then(o=>pc.setLocalDescription(o))
      .then(()=>io_.emit("offer",pc.localDescription.toJSON()));
  }else{
    pc.ondatachannel=e=>{dc=e.channel;bindDC(dc)};
  }
}

function bindDC(ch){
  ch.onopen=()=>{setConn();add("Connected peer-to-peer! Say hi!","s")};
  ch.onclose=()=>{
    if(matched){setDC();add("Stranger has disconnected.","s");showFindNew()}
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

// ── P2P messaging ───────────────────────────────────────────────────────────
function dcSend(obj){if(dc&&dc.readyState==="open")dc.send(JSON.stringify(obj))}

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
