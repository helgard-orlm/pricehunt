const api = typeof browser !== "undefined" ? browser : chrome;
async function show() {
  const s = await api.storage.local.get("server");
  document.getElementById("srv").value = s.server || "http://192.168.1.107:8931";
  const st = await api.runtime.sendMessage({ kind: "status" });
  const el = document.getElementById("st");
  el.className = st && st.connected ? "ok" : "bad";
  el.textContent = st && st.connected
    ? `на связи · открыто страниц: ${st.done}${st.current ? " · сейчас " + st.current : ""}`
    : "нет связи с сервером" + (st && st.lastError ? " (" + st.lastError + ")" : "");
}
document.getElementById("save").onclick = async () => {
  await api.storage.local.set({ server: document.getElementById("srv").value.trim() });
  await api.runtime.sendMessage({ kind: "reconnect" });
  setTimeout(show, 1500);
};
show();
setInterval(show, 2000);
