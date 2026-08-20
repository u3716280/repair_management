(() => {
  "use strict";

  const apiBase = "/api/method/repair_management.integrations.line.delivery_confirmation.api";
  const $ = (id) => document.getElementById(id);
  const views = ["loading", "scan-view", "order-view", "evidence-view", "success-view"];
  const state = {
    channelName: "", liffId: "", idToken: "", order: null,
    location: null, photos: [], submitting: false, requestId: null,
  };

  const hide = (el) => el && el.classList.add("hidden");
  const show = (el) => el && el.classList.remove("hidden");
  function showView(id) { views.forEach((name) => $(name).classList.toggle("hidden", name !== id)); }
  function notice(message, error=false) {
    const el = $("notice");
    if (!message) { hide(el); return; }
    el.textContent = message; el.classList.toggle("error", error); show(el);
  }

  async function jsonPost(method, payload={}) {
    const body = new URLSearchParams(payload);
    const response = await fetch(`${apiBase}.${method}`, {
      method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"},
      body, credentials:"omit",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.exc) throw new Error(extractMessage(data));
    return data.message;
  }
  function extractMessage(data) {
    if (data && data._server_messages) {
      try {
        const rows = JSON.parse(data._server_messages);
        if (rows.length) return JSON.parse(rows[0]).message || "request_failed";
      } catch (_) {}
    }
    return (data && (data.exception || data.message)) || "request_failed";
  }

  function newRequestId() {
    return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  async function bootstrap() {
    try {
      const config = await jsonPost("config");
      state.channelName = config.channel_name;
      state.liffId = config.liff_id;
      await liff.init({liffId: state.liffId});
      if (!liff.isLoggedIn()) { liff.login(); return; }
      state.idToken = liff.getIDToken() || "";
      if (!state.idToken) throw new Error("missing_id_token");
      await jsonPost("bootstrap", {id_token:state.idToken, channel_name:state.channelName});
      resetAll(); showView("scan-view");
    } catch (error) {
      showView("loading");
      $("loading").textContent = "ไม่สามารถเปิด Proof of Delivery ได้";
      notice(error.message || "ไม่สามารถเข้าสู่ระบบได้", true);
    }
  }

  async function scan() {
    notice("");
    if (!liff.scanCodeV2) { notice("อุปกรณ์นี้ไม่รองรับ LINE QR Scanner", true); return; }
    try {
      const result = await liff.scanCodeV2();
      const value = (result && result.value ? result.value : "").trim();
      if (!value) return;
      const view = await jsonPost("scan_sales_order", {
        id_token:state.idToken, channel_name:state.channelName, sales_order:value,
      });
      state.order = view;
      state.requestId = newRequestId();
      $("sales-order").textContent = view.sales_order;
      $("customer-name").textContent = view.customer_name || view.customer || "-";
      showView("order-view");
    } catch (error) { notice(error.message || "สแกนไม่สำเร็จ", true); }
  }

  function getLocationOnce() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) { reject(new Error("อุปกรณ์นี้ไม่รองรับการระบุตำแหน่ง")); return; }
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({
          latitude:pos.coords.latitude, longitude:pos.coords.longitude,
          accuracy:pos.coords.accuracy, timestamp:new Date(pos.timestamp).toISOString(),
        }),
        () => reject(new Error("ไม่สามารถรับพิกัดได้ กรุณาอนุญาต Location แล้วลองใหม่")),
        {enableHighAccuracy:true, timeout:15000, maximumAge:0},
      );
    });
  }

  async function continueToEvidence() {
    notice(""); showView("evidence-view");
    $("location-status").textContent = "กำลังรับพิกัด...";
    try {
      state.location = await getLocationOnce();
      $("location-status").textContent = `บันทึกพิกัดแล้ว · Accuracy ±${Math.round(state.location.accuracy || 0)} m`;
      renderPhotos();
    } catch (error) {
      state.location = null;
      $("location-status").textContent = "ยังไม่ได้พิกัด";
      notice(error.message, true);
    }
  }

  function renderPhotos() {
    const box = $("photos"); box.innerHTML = "";
    state.photos.forEach((entry, index) => {
      const card = document.createElement("div"); card.className = "photo-card";
      const img = document.createElement("img"); img.src = entry.url; img.alt = `Photo ${index+1}`;
      const remove = document.createElement("button"); remove.type="button"; remove.className="photo-remove"; remove.textContent="×";
      remove.addEventListener("click", () => { URL.revokeObjectURL(entry.url); state.photos.splice(index,1); renderPhotos(); });
      card.append(img, remove); box.appendChild(card);
    });
    $("photo-count").textContent = `${state.photos.length} / 8 รูป`;
    $("camera-button").disabled = state.photos.length >= 8;
    $("confirm-button").disabled = !(state.location && state.photos.length >= 1 && !state.submitting);
  }

  function addCameraPhoto(file) {
    if (!file || !file.type.startsWith("image/")) { notice("รองรับเฉพาะรูปภาพ", true); return; }
    if (state.photos.length >= 8) { notice("ถ่ายได้สูงสุด 8 รูป", true); return; }
    state.photos.push({file, url:URL.createObjectURL(file)}); renderPhotos();
  }

  async function reportChatNotification(confirmation, status, error="") {
    try {
      await jsonPost("report_chat_notification", {
        id_token:state.idToken,
        channel_name:state.channelName,
        confirmation,
        status,
        error:error || "",
      });
    } catch (_) {
      // POD is already confirmed. Notification status reporting is best-effort only.
    }
  }

  async function sendPodToChat(result) {
    if (!liff.sendMessages) throw new Error("LINE chat_message.write ไม่พร้อมใช้งาน");
    const text = result.chat_text || `[POD] ส่งของแล้ว ${result.sales_order || ""}`.trim();
    await liff.sendMessages([{type:"text", text}]);
  }

  async function confirmPod() {
    if (state.submitting || !state.order || !state.location || !state.photos.length) return;
    state.submitting = true; renderPhotos(); notice("");
    const btn = $("confirm-button"); btn.textContent = "กำลังยืนยัน...";
    try {
      if (!state.requestId) state.requestId = newRequestId();
      const form = new FormData();
      form.append("id_token", state.idToken);
      form.append("channel_name", state.channelName);
      form.append("sales_order", state.order.sales_order);
      form.append("request_id", state.requestId);
      form.append("latitude", state.location.latitude);
      form.append("longitude", state.location.longitude);
      form.append("accuracy", state.location.accuracy || "");
      form.append("location_timestamp", state.location.timestamp || "");
      state.photos.forEach((entry) => form.append("photos", entry.file, entry.file.name || "camera.jpg"));
      const response = await fetch(`${apiBase}.confirm`, {method:"POST", body:form, credentials:"omit"});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.exc) throw new Error(extractMessage(data));
      const result = data.message;

      $("success-order").textContent = result.sales_order;
      $("success-customer").textContent = result.customer_name || "";
      $("success-target").textContent = `แนบ ${result.photo_count} รูป → ${result.attachment_target.doctype} ${result.attachment_target.name}`;
      $("success-chat").textContent = "กำลังส่งข้อความเข้า LINE Chat...";
      showView("success-view");

      try {
        await sendPodToChat(result);
        $("success-chat").textContent = "ส่งข้อความยืนยันเข้า LINE Chat แล้ว";
        await reportChatNotification(result.confirmation, "Sent");
      } catch (chatError) {
        $("success-chat").textContent = "บันทึก POD สำเร็จ แต่ส่งข้อความเข้า LINE Chat ไม่สำเร็จ";
        await reportChatNotification(result.confirmation, "Failed", chatError.message || "sendMessages_failed");
      }
    } catch (error) {
      // Keep requestId after ambiguous/network errors so retry can resolve an already
      // confirmed transaction instead of creating duplicate POD files.
      if ((error.message || "").includes("request_id นี้เคยประมวลผลไม่สำเร็จ")) {
        state.requestId = newRequestId();
      }
      notice(error.message || "ยืนยันการจัดส่งไม่สำเร็จ", true);
    } finally {
      state.submitting = false; btn.textContent = "ยืนยันการจัดส่ง"; renderPhotos();
    }
  }

  function clearPhotos() { state.photos.forEach((p) => URL.revokeObjectURL(p.url)); state.photos=[]; }
  function resetAll() {
    clearPhotos(); state.order=null; state.location=null; state.submitting=false; state.requestId=null;
    $("camera-input").value=""; notice(""); renderPhotos();
  }
  function rescan() { resetAll(); showView("scan-view"); scan(); }

  $("scan-button").addEventListener("click", scan);
  $("rescan-button").addEventListener("click", rescan);
  $("continue-button").addEventListener("click", continueToEvidence);
  $("evidence-rescan").addEventListener("click", () => {
    if (state.photos.length && !window.confirm("รูปและพิกัดที่ยังไม่ได้ยืนยันจะถูกทิ้ง ต้องการสแกนใหม่หรือไม่?")) return;
    rescan();
  });
  $("camera-button").addEventListener("click", () => $("camera-input").click());
  $("camera-input").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0]; addCameraPhoto(file); event.target.value="";
  });
  $("confirm-button").addEventListener("click", confirmPod);
  $("next-button").addEventListener("click", () => { resetAll(); showView("scan-view"); });

  bootstrap();
})();
