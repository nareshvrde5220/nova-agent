document.addEventListener("DOMContentLoaded", () => {
  const socket = io();
  const micBtn = document.getElementById("micBtn");
  const startSessionBtn = document.getElementById("startSessionBtn");
  const endSessionBtn = document.getElementById("endSessionBtn");
  const chatBox = document.getElementById("chatBox");
  const audioPlayer = document.getElementById("audioPlayer");

  if (
    !startSessionBtn ||
    !micBtn ||
    !endSessionBtn ||
    !chatBox ||
    !audioPlayer
  ) {
    console.error("One or more DOM elements not found:", {
      startSessionBtn,
      micBtn,
      endSessionBtn,
      chatBox,
      audioPlayer,
    });
    return;
  }

  let isRecording = false;
  let isSessionActive = false;
  let currentSessionId = null;

  socket.on("connect", () => {
    console.log("Socket.IO connected");
    startSessionBtn.disabled = false;
  });

  socket.on("connect_error", (error) => {
    console.error("Socket.IO connection error:", error);
    appendReplyMessage("Error: Failed to connect to the server.");
  });

  socket.on("nova_session_started", (data) => {
    isSessionActive = true;
    currentSessionId = data.session_id;
    console.log("[INFO] Nova session started:", currentSessionId);

    // Show chat box
    chatBox.classList.add("active");
    console.log("Chat box classes:", chatBox.classList);

    micBtn.disabled = false;
    startSessionBtn.disabled = true;
    endSessionBtn.disabled = false;

    // Auto-start microphone
    if (!isRecording) {
      console.log("Attempting to auto-click mic button");
      setTimeout(() => {
        micBtn.click();
      }, 500);
    }
  });

  socket.on("assistant_message", (data) => {
    console.log("Assistant message received:", data.text);
    appendReplyMessage(data.text);
  });

  socket.on("user_message", (data) => {
    appendUserMessage(data.text);
  });

  socket.on("audio_output", (data) => {
    playAudio(data.audio);
  });

  socket.on("error", (data) => {
    appendReplyMessage(`Error: ${data.message}`);
  });

  socket.on("nova_session_stopped", () => {
    resetUI();
  });

  function resetUI() {
    isRecording = false;
    isSessionActive = false;
    micBtn.classList.remove("recording");
    micBtn.disabled = true;
    startSessionBtn.disabled = false;
    endSessionBtn.disabled = true;
    chatBox.classList.remove("active");
    clearAudioQueue();
  }

  // Audio playback queue
  const audioQueue = [];
  let isPlaying = false;

  function playAudio(base64Audio) {
    const audioBlob = base64ToBlob(base64Audio, "audio/wav");
    audioQueue.push(audioBlob);

    if (!isPlaying) {
      playNextAudio();
    }
  }

  function playNextAudio() {
    if (audioQueue.length === 0) {
      isPlaying = false;
      return;
    }

    isPlaying = true;
    const nextAudioBlob = audioQueue.shift();
    const audioUrl = URL.createObjectURL(nextAudioBlob);

    audioPlayer.src = audioUrl;
    audioPlayer.play().catch((e) => {
      console.error("Audio play failed:", e);
      isPlaying = false;
    });

    audioPlayer.onended = () => {
      URL.revokeObjectURL(audioUrl);
      playNextAudio();
    };
  }

  function clearAudioQueue() {
    audioQueue.length = 0;
    isPlaying = false;
    audioPlayer.pause();
    audioPlayer.src = "";
  }

  function base64ToBlob(base64, mimeType) {
    const byteCharacters = atob(base64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    return new Blob([byteArray], { type: mimeType });
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioContext = new AudioContext({ sampleRate: 16000 });
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);

      processor.onaudioprocess = function (e) {
        if (isRecording) {
          const inputData = e.inputBuffer.getChannelData(0);
          const int16Data = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            int16Data[i] = Math.max(
              -32768,
              Math.min(32767, inputData[i] * 32768)
            );
          }
          const arrayBuffer = int16Data.buffer;
          const base64Audio = btoa(
            String.fromCharCode(...new Uint8Array(arrayBuffer))
          );
          socket.emit("audio_data", { audio: base64Audio });
        }
      };

      source.connect(processor);
      processor.connect(audioContext.destination);
      window.audioStream = stream;
      window.audioContext = audioContext;
      window.audioProcessor = processor;
      socket.emit("start_recording");
    } catch (error) {
      console.error("Error starting recording:", error);
      appendReplyMessage("Error: Microphone access issue.");
    }
  }

  function stopRecording() {
    if (window.audioStream)
      window.audioStream.getTracks().forEach((track) => track.stop());
    if (window.audioProcessor) window.audioProcessor.disconnect();
    if (window.audioContext) window.audioContext.close();
    window.audioStream = null;
    window.audioContext = null;
    window.audioProcessor = null;
    socket.emit("stop_recording");
  }

  startSessionBtn.addEventListener("click", () => {
    console.log("Start Conversation button clicked");
    socket.emit("start_nova_session");
    appendReplyMessage("Starting underwriting conversation with Alan...");
  });

  endSessionBtn.addEventListener("click", () => {
    console.log("End Conversation button clicked");
    if (isRecording) stopRecording();
    socket.emit("end_nova_session");
    resetUI();
    appendReplyMessage("Conversation ended.");
  });

  micBtn.addEventListener("click", () => {
    console.log("Mic button clicked, isSessionActive:", isSessionActive);
    if (!isSessionActive) return;
    if (!isRecording) {
      startRecording();
      isRecording = true;
      micBtn.classList.add("recording");
      micBtn.textContent = "⏹️";
    } else {
      stopRecording();
      isRecording = false;
      micBtn.classList.remove("recording");
      micBtn.textContent = "🎤";
    }
  });

  function appendUserMessage(message) {
    const $chatContainer = $(".chat-list ul");
    if (!$chatContainer.length) {
      console.error("Chat container not found");
      return;
    }

    const $li = $("<li>").addClass("d-flex justify-content-end mb-4");
    const $card = $("<div>").addClass("card w-100");
    const $cardBody = $("<div>").addClass("card-body");
    const $p = $("<p>").addClass("mb-0").text(message);

    const loaderSVG = `
            <svg class="chat-load" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid">
                <g transform="translate(20 50)">
                    <circle cx="0" cy="0" r="6" fill="#000000">
                        <animateTransform attributeName="transform" type="scale" begin="-0.375s"
                            calcMode="spline" keySplines="0.3 0 0.7 1;0.3 0 0.7 1"
                            values="0;1;0" keyTimes="0;0.5;1" dur="1s" repeatCount="indefinite" />
                    </circle>
                </g>
                <g transform="translate(40 50)">
                    <circle cx="0" cy="0" r="6" fill="#72cbfd">
                        <animateTransform attributeName="transform" type="scale" begin="-0.25s"
                            calcMode="spline" keySplines="0.3 0 0.7 1;0.3 0 0.7 1"
                            values="0;1;0" keyTimes="0;0.5;1" dur="1s" repeatCount="indefinite" />
                    </circle>
                </g>
                <g transform="translate(60 50)">
                    <circle cx="0" cy="0" r="6" fill="#0079c2">
                        <animateTransform attributeName="transform" type="scale" begin="-0.125s"
                            calcMode="spline" keySplines="0.3 0 0.7 1;0.3 0 0.7 1"
                            values="0;1;0" keyTimes="0;0.5;1" dur="1s" repeatCount="indefinite" />
                    </circle>
                </g>
                <g transform="translate(80 50)">
                    <circle cx="0" cy="0" r="6" fill="#ff6600">
                        <animateTransform attributeName="transform" type="scale" begin="0s"
                            calcMode="spline" keySplines="0.3 0 0.7 1;0.3 0 0.7 1"
                            values="0;1;0" keyTimes="0;0.5;1" dur="1s" repeatCount="indefinite" />
                    </circle>
                </g>
            </svg>`;

    const $loader = $(loaderSVG).addClass("chat-loader");

    const $avatar = $("<img>", {
      src: "/static/images/you.png",
      alt: "avatar",
      width: 60,
      class: "rounded-circle d-flex align-self-start ms-3 shadow-1-strong",
    });

    $cardBody.append($p, $loader);
    $card.append($cardBody);
    $li.append($card, $avatar);
    $chatContainer.append($li);

    setTimeout(() => {
      removeUserLoader();
    }, 2000);
  }

  function removeUserLoader() {
    const $loader = $(".chat-list ul li .chat-loader").last();
    $loader.fadeOut(300, function () {
      $loader.remove();
    });
  }

  function appendReplyMessage(reply) {
    const chatContainer = document.querySelector(".chat-list ul");
    if (!chatContainer) {
      console.error("Chat list container not found");
      return;
    }

    const li = document.createElement("li");
    li.className = "d-flex justify-content-start mb-4";

    const avatar = document.createElement("img");
    avatar.src = "/static/images/Chat-bot-head.svg";
    avatar.alt = "avatar";
    avatar.className =
      "rounded-circle d-flex align-self-start me-3 shadow-1-strong";
    avatar.width = 60;

    const card = document.createElement("div");
    card.className = "card chat-reply-box w-100";

    const cardBody = document.createElement("div");
    cardBody.className = "card-body";

    const p = document.createElement("p");
    p.className = "mb-0";
    p.innerHTML = reply;

    cardBody.appendChild(p);
    card.appendChild(cardBody);

    li.appendChild(avatar);
    li.appendChild(card);
    chatContainer.appendChild(li);

    jQuery(".chat-list").animate(
      { scrollTop: $(".chat-list").prop("scrollHeight") },
      1000
    );
    jQuery("#collapseExample").collapse("show");
  }
});
