# TalkToMe — Requirements Document

> An Omegle-style anonymous live chat application.

---

## 1. Overview

TalkToMe connects two random strangers for a real-time, anonymous one-on-one chat session. Users can text chat (and optionally video chat) with no sign-up required.

---

## 2. Core Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | **Random Matching** | Pair two online users at random into a private chat room. |
| 2 | **Text Chat** | Real-time message exchange via WebSockets. |
| 3 | **Video Chat** | Peer-to-peer video/audio using WebRTC. |
| 4 | **Anonymous** | No login, no accounts — just click and chat. |
| 5 | **Skip / Next** | Either user can end the chat and get matched with someone new. |
| 6 | **Typing Indicator** | Show "Stranger is typing…" in real time. |
| 7 | **Interest Tags** (optional) | Users can enter interests to be matched with like-minded strangers. |
| 8 | **Online Count** | Display how many users are currently online. |

---

## 3. Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React (Vite), TailwindCSS |
| **Backend** | Node.js, Express |
| **Real-time** | Socket.IO (signaling + text chat) |
| **Video** | WebRTC (peer-to-peer), STUN/TURN servers |
| **Deployment** | Docker, any VPS / cloud provider |

---

## 4. Architecture (High-Level)

```
┌──────────┐   WebSocket    ┌──────────────┐
│  Client  │ ◄────────────► │  Node.js     │
│ (React)  │                │  Server      │
└──────────┘                │  (Socket.IO) │
      ▲                     └──────┬───────┘
      │  WebRTC (P2P)              │
      ▼                     Matching Queue
┌──────────┐                & Room Manager
│  Client  │
│ (React)  │
└──────────┘
```

---

## 5. User Flow

1. User lands on homepage → sees "Start Chat" button and online count.
2. (Optional) User enters interest tags.
3. User clicks **Start** → enters waiting queue.
4. Server matches two queued users → creates a private room.
5. Users exchange text messages (and/or enable video).
6. Either user clicks **Next** → disconnected, re-enters queue.
7. Either user clicks **Disconnect** → returns to homepage.

---

## 6. Key Socket Events

| Event | Direction | Purpose |
|-------|-----------|---------|
| `join-queue` | Client → Server | User wants to be matched |
| `matched` | Server → Client | Two users paired, room ID sent |
| `send-message` | Client → Server | Chat message sent |
| `receive-message` | Server → Client | Chat message delivered |
| `typing` | Client → Server → Client | Typing indicator |
| `skip` | Client → Server | User wants a new partner |
| `partner-disconnected` | Server → Client | Other user left |
| `webrtc-offer/answer/ice` | Client ↔ Server | WebRTC signaling |

---

## 7. Non-Functional Requirements

- **Latency**: Messages delivered in < 100ms on average.
- **Scalability**: Support 1,000+ concurrent users per server instance.
- **Privacy**: No messages stored on the server; ephemeral only.
- **Moderation** (future): Report button, basic profanity filter.
- **Responsive UI**: Works on desktop and mobile browsers.

---

## 8. MVP Scope (Phase 1)

- [x] Random text chat matching
- [x] Real-time messaging via WebSockets
- [x] Skip / Next / Disconnect
- [x] Typing indicator
- [x] Online user count
- [ ] Video chat (Phase 2)
- [ ] Interest-based matching (Phase 2)
- [ ] Moderation tools (Phase 3)

---

*Ready to build. 🚀*
