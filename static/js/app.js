const state = { data: null, visible: 0, timer: null };
let currentProgress = 0;

function money(value) {
  return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(value);
}

function selectedSpeed() {
  return Number(document.querySelector("#speedSelect").value);
}

function updateLuffyPosition(progress = currentProgress) {
  const track = document.querySelector("#progressTrack");
  const luffy = document.querySelector("#luffyGif");
  const travel = Math.max(0, track.clientWidth - luffy.offsetWidth);
  luffy.style.transform = `translateX(${travel * progress / 100}px) scaleX(-1)`;
}

function updateLabels() {
  const count = state.data?.count || 0;
  const visible = Math.min(state.visible, count);
  const day = visible > 0 ? state.data.days[visible - 1] : null;
  document.querySelector("#dayNumber").textContent = visible;
  document.querySelector("#dayCount").textContent = count;
  const progress = count > 0 ? Math.max(0, Math.min(100, Math.round((visible / count) * 100))) : 0;
  currentProgress = progress;
  document.querySelector("#chartProgress").value = progress;
  document.querySelector("#chartProgress").setAttribute("aria-valuenow", progress);
  document.querySelector("#progressValue").textContent = `${progress}%`;
  updateLuffyPosition(progress);

  if (day) {
    document.querySelector("#lastPrice").textContent = money(day.close);
    document.querySelector("#chartHint").textContent =
      `Ngày ${day.day}: tham chiếu ${money(day.reference)} · sàn ${money(day.floor)} · trần ${money(day.ceiling)}`;
  } else {
    document.querySelector("#lastPrice").textContent = "—";
    document.querySelector("#chartHint").textContent = state.data
      ? "Chọn ngày hoặc chạy biểu đồ để bắt đầu"
      : "Đang chờ dữ liệu biểu đồ";
  }
}

function syncPlaybackControls() {
  const playing = Boolean(state.timer);
  const topButton = document.querySelector("#playButton");
  topButton.textContent = playing ? "Ⅱ Tạm dừng" : "▶ Chạy biểu đồ";
  topButton.setAttribute("aria-label", playing ? "Pause chart" : "Run chart");
}

function render() {
  updateLabels();
  TradingChart.setVisible(state.visible);
}

function stop() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  syncPlaybackControls();
}

function play() {
  if (!state.data || !state.data.count) return;
  if (state.visible >= state.data.count) state.visible = 0;
  stop();
  state.timer = setInterval(() => {
    state.visible = Math.min(state.visible + 1, state.data.count);
    render();
    if (state.visible >= state.data.count) stop();
  }, selectedSpeed());
  syncPlaybackControls();
}

function applyData(nextData) {
  stop();
  state.data = nextData;
  state.visible = 0;
  document.querySelector("#symbol").textContent = state.data.symbol;
  document.querySelector("#statusText").textContent = `Đã tải ${nextData.count} ngày dữ liệu`;

  const warnEl = document.querySelector("#warningBanner");
  if (warnEl) {
    if (nextData.warnings && nextData.warnings.length > 0) {
      const preview = nextData.warnings.slice(0, 2).join(" | ");
      const more = nextData.warnings.length > 2
        ? ` … (+${nextData.warnings.length - 2} ngày khác)`
        : "";
      warnEl.textContent = `⚠ ${nextData.warnings.length} ngày có giá ngoài biên: ${preview}${more}`;
      warnEl.style.display = "block";
    } else {
      warnEl.style.display = "none";
      warnEl.textContent = "";
    }
  }

  TradingChart.setData(state.data);
  render();
}

async function load(url) {
  stop();
  const response = await fetch(url);
  if (!response.ok) throw new Error((await response.json()).detail || "Không tải được dữ liệu.");
  applyData(await response.json());
}

TradingChart.setup(document.querySelector("#priceChart"));
document.querySelector("#luffyGif").addEventListener("error", (event) => {
  event.currentTarget.hidden = true;
  event.currentTarget.closest(".progress-track").classList.add("no-luffy");
});
document.querySelector("#luffyGif").addEventListener("load", () => updateLuffyPosition());
window.addEventListener("resize", () => updateLuffyPosition());
document.querySelector("#playButton").addEventListener("click", () =>
  state.timer ? stop() : play()
);
document.querySelector("#resetButton").addEventListener("click", () => {
  stop();
  state.visible = 0;
  render();
});
document.querySelector("#speedSelect").addEventListener("change", () => {
  if (state.timer) play();
});
document.querySelector("#fileInput").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/data/upload", { method: "POST", body: form });
  if (!response.ok) {
    document.querySelector("#statusText").textContent = (await response.json()).detail;
    return;
  }
  applyData(await response.json());
});

load("/api/data").catch((error) => {
  document.querySelector("#statusText").textContent = error.message;
});
