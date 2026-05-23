const container = document.getElementById('stars');
for (let i = 0; i < 120; i++) {
  const s = document.createElement('div');
  s.className = 'star';
  s.style.cssText = `
    left:${Math.random()*100}%;
    top:${Math.random()*100}%;
    --d:${2 + Math.random()*4}s;
    --delay:-${Math.random()*5}s;
    --bright:${0.4 + Math.random()*0.6};
    width:${Math.random() > 0.85 ? 3 : 2}px;
    height:${Math.random() > 0.85 ? 3 : 2}px;
  `;
  container.appendChild(s);
}
