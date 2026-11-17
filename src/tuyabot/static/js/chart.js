/**
 * Grafik garis/area sederhana di canvas — tanpa library eksternal.
 * Input: array titik {t: epoch_ms, v: watt}, urut naik berdasarkan waktu.
 */

const COLORS = {
  line: '#22d3ee',
  fillTop: 'rgba(34, 211, 238, 0.32)',
  fillBottom: 'rgba(34, 211, 238, 0.02)',
  grid: 'rgba(255, 255, 255, 0.07)',
  axis: '#64748b',
  peak: '#fbbf24',
};

function niceMax(value) {
  if (!Number.isFinite(value) || value <= 0) return 10;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

export function drawPowerChart(canvas, points) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth || canvas.parentElement.clientWidth || 640;
  const cssHeight = canvas.clientHeight || Number(canvas.getAttribute('height')) || 220;

  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  if (!points.length) return;

  const padding = { top: 16, right: 14, bottom: 26, left: 44 };
  const plotWidth = Math.max(10, cssWidth - padding.left - padding.right);
  const plotHeight = Math.max(10, cssHeight - padding.top - padding.bottom);

  const values = points.map((p) => p.v);
  const maxValue = niceMax(Math.max(...values, 1));
  const minTime = points[0].t;
  const maxTime = points[points.length - 1].t;
  const span = Math.max(1, maxTime - minTime);

  const x = (t) => padding.left + ((t - minTime) / span) * plotWidth;
  const y = (v) => padding.top + plotHeight - (Math.max(0, v) / maxValue) * plotHeight;

  // Grid horizontal + label sumbu Y
  ctx.strokeStyle = COLORS.grid;
  ctx.fillStyle = COLORS.axis;
  ctx.font = '11px ui-monospace, monospace';
  ctx.lineWidth = 1;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i += 1) {
    const value = (maxValue / 4) * i;
    const lineY = y(value);
    ctx.beginPath();
    ctx.moveTo(padding.left, lineY);
    ctx.lineTo(cssWidth - padding.right, lineY);
    ctx.stroke();
    ctx.fillText(`${Math.round(value)}`, padding.left - 8, lineY);
  }

  // Area
  const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + plotHeight);
  gradient.addColorStop(0, COLORS.fillTop);
  gradient.addColorStop(1, COLORS.fillBottom);
  ctx.beginPath();
  ctx.moveTo(x(points[0].t), y(points[0].v));
  points.forEach((point) => ctx.lineTo(x(point.t), y(point.v)));
  ctx.lineTo(x(points[points.length - 1].t), padding.top + plotHeight);
  ctx.lineTo(x(points[0].t), padding.top + plotHeight);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  // Garis
  ctx.beginPath();
  points.forEach((point, index) => {
    const px = x(point.t);
    const py = y(point.v);
    if (index === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.strokeStyle = COLORS.line;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.stroke();

  // Titik puncak
  const peakIndex = values.indexOf(Math.max(...values));
  const peak = points[peakIndex];
  ctx.beginPath();
  ctx.arc(x(peak.t), y(peak.v), 3.5, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.peak;
  ctx.fill();

  // Label sumbu X (awal, tengah, akhir) — label tepi dirapatkan agar tidak terpotong.
  ctx.fillStyle = COLORS.axis;
  ctx.textBaseline = 'top';
  const labels = [
    { point: points[0], align: 'left', x: padding.left },
    { point: points[Math.floor(points.length / 2)], align: 'center', x: x(points[Math.floor(points.length / 2)].t) },
    { point: points[points.length - 1], align: 'right', x: cssWidth - padding.right },
  ];
  labels.forEach(({ point, align, x: labelX }) => {
    const label = new Date(point.t).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
    ctx.textAlign = align;
    ctx.fillText(label, labelX, padding.top + plotHeight + 8);
  });
}
