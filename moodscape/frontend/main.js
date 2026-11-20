import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const API = (typeof window !== 'undefined' && window.MOODSCAPE_API_URL) || (typeof localStorage !== 'undefined' && localStorage.getItem('ms_api')) || 'http://localhost:8000';

// --- 会话身份 / 订阅 / 社交状态 ------------------------------------------
let CURRENT_USER = parseInt(new URLSearchParams(location.search).get('user') || localStorage.getItem('ms_user') || '1', 10);
const PARTNER_ID = parseInt(new URLSearchParams(location.search).get('partner') || '2', 10);
let currentTheme = null;   // premium 材质 (null = 原生)
let bondId = null;         // 双岛连接 id
let mediaRecorder = null;
let audioChunks = [];

// AI 观察者克制在场：指向环境，不诊断心理，不超过两行
// 默认沉默：AI 不主动弹话，只在景观表面浮现可触摸的高光，由用户主动叩问。
const OBSERVER_LINES = {
  anxious: '云压得很低，风在岛上走得很急。',
  calm: '水母浮得很慢，连光都慢了下来。',
  lonely: '岛上的那盏灯，一直亮着。',
  happy: '花在开，光在轻轻跳。',
  sad: '雨落在岛心，很轻很轻。',
  neutral: '雾还没散。',
};

// 沉默被完整支持：可永久关闭 AI 回应，设置保存在本地。
let aiMuted = localStorage.getItem('ms_ai_muted') === '1';

// 光学浓度随活跃度自然衰减：仅通过在场强度表达，不做"正在输入"
let presenceSocket = null;
let presenceLevel = 1.0;
let lastActivity = Date.now();


const PALETTES = {
  anxious: ['#4A5568', '#2D3748', '#718096'],
  calm: ['#B2F5EA', '#81E6D9', '#C6F6D5'],
  lonely: ['#1A202C', '#2D3748', '#4A5568'],
  happy: ['#FBD38D', '#F6AD55', '#FEEBC8'],
  sad: ['#A0AEC0', '#718096', '#4A5568'],
  neutral: ['#E2E8F0', '#CBD5E0', '#A0AEC0'],
};
const TERRAINS = { anxious:'jagged', calm:'rolling', lonely:'mound', happy:'plateau', sad:'basin', neutral:'flat' };
const PARTICLES = { anxious:'sparks', calm:'petals', lonely:'stars', happy:'bubbles', sad:'rain', neutral:'mist' };
const TENSIONS = { anxious:0.9, calm:0.2, lonely:0.4, happy:0.3, sad:0.6, neutral:0.5 };
const ENERGIES = { anxious:0.85, calm:0.15, lonely:0.1, happy:0.9, sad:0.2, neutral:0.5 };

function mockParams(text) {
  const lower = text.toLowerCase();
  let mood = 'neutral';
  const zhMap = { '焦虑':'anxious','不安':'anxious','平静':'calm','放松':'calm','安宁':'calm','孤独':'lonely','寂寞':'lonely','开心':'happy','高兴':'happy','幸福':'happy','难过':'sad','悲伤':'sad','伤心':'sad','下雨':'sad' };
  for (const k in zhMap) { if (text.indexOf(k) >= 0) { mood = zhMap[k]; break; } }
  for (const m of ['anxious','calm','lonely','happy','sad']) { if (lower.indexOf(m) >= 0) { mood = m; break; } }
  return {
    mood: mood,
    palette: PALETTES[mood],
    terrain: TERRAINS[mood],
    particles: PARTICLES[mood],
    energy: ENERGIES[mood],
    valence: 0.5,
    tension: TENSIONS[mood],
    clarity: 1 - TENSIONS[mood],
    weather: mood,
  };
}

// --- 噪声与地形 -------------------------------------------------------------
function makeNoise(seed) {
  function rand(ix, iy) {
    const x = Math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453;
    return x - Math.floor(x);
  }
  function smooth(t) { return t * t * (3 - 2 * t); }
  function noise(x, y) {
    const ix = Math.floor(x), iy = Math.floor(y);
    const fx = x - ix, fy = y - iy;
    const a = rand(ix, iy), b = rand(ix + 1, iy), c = rand(ix, iy + 1), d = rand(ix + 1, iy + 1);
    const ux = smooth(fx), uy = smooth(fy);
    return a * (1 - ux) * (1 - uy) + b * ux * (1 - uy) + c * (1 - ux) * uy + d * ux * uy;
  }
  return function fbm(x, y, oct) {
    let v = 0, amp = 0.5, f = 1, norm = 0;
    for (let i = 0; i < oct; i++) { v += amp * noise(x * f, y * f); norm += amp; amp *= 0.5; f *= 2; }
    return v / norm;
  };
}
const noise2 = makeNoise(3);

function terrainHeight(x, y, type, tension) {
  const n = noise2(x * 0.18, y * 0.18, 4);
  const d = Math.sqrt(x * x + y * y);
  if (type === 'jagged') {
    return (n - 0.5) * 2 * tension * 6 + Math.abs(n - 0.5) * tension * 4;
  } else if (type === 'rolling') {
    return Math.sin(x * 0.25) * Math.cos(y * 0.25) * tension * 2.2 + (n - 0.5) * 1.2;
  } else if (type === 'mound') {
    return Math.max(0, 3.2 - d * 0.35) * (0.7 + tension * 0.5) + (n - 0.5) * 0.6;
  } else if (type === 'basin') {
    return -Math.max(0, 2.5 - d * 0.3) + (n - 0.5) * 1.0;
  } else if (type === 'plateau') {
    return (n - 0.5) * 1.4 + Math.sin(x * 0.15) * 0.4;
  }
  return (n - 0.5) * 1.0;
}

// --- 渲染器 -----------------------------------------------------------------
class IslandRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 200);
    this.renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(window.innerWidth, window.innerHeight);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;

    this.clock = new THREE.Clock();
    this.fragments = [];
    this.particleType = 'mist';
    this.particleEnergy = 0.5;
    this.current = null;

    this.camera.position.set(14, 12, 16);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.autoRotate = true;
    this.controls.autoRotateSpeed = 0.3;
    this.controls.minDistance = 8;
    this.controls.maxDistance = 40;
    this.controls.maxPolarAngle = Math.PI * 0.6;
    this.controls.target.set(0, 1, 0);

    this.initLights();
    this.initIsland();
    this.initParticles();
    this.initInteractions();

    window.addEventListener('resize', () => this.onResize());
    this.animate();
  }

  initLights() {
    this.ambient = new THREE.AmbientLight(0xffffff, 0.6);
    this.scene.add(this.ambient);
    this.hemi = new THREE.HemisphereLight(0xbfd8ff, 0x1a1a24, 0.6);
    this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight(0xffffff, 1.2);
    this.sun.position.set(10, 16, 8);
    this.scene.add(this.sun);
  }

  initIsland() {
    this.islandGroup = new THREE.Group();
    this.scene.add(this.islandGroup);

    this.surfaceGeo = new THREE.PlaneGeometry(30, 30, 100, 100);
    this.surfaceMat = new THREE.MeshStandardMaterial({ color: 0xe2e8f0, flatShading: true, roughness: 0.85, metalness: 0.05 });
    this.surface = new THREE.Mesh(this.surfaceGeo, this.surfaceMat);
    this.surface.rotation.x = -Math.PI / 2;
    this.islandGroup.add(this.surface);

    const rock = new THREE.Mesh(
      new THREE.ConeGeometry(14, 8, 48),
      new THREE.MeshStandardMaterial({ color: 0x2a2a30, flatShading: true, roughness: 0.9 })
    );
    rock.position.y = -4.2;
    this.rock = rock;
    this.islandGroup.add(rock);

    this.scene.fog = new THREE.FogExp2(0x0a0a12, 0.014);
    this.scene.background = new THREE.Color(0x0a0a12);
    this.applyTerrain('flat', 0.5);
  }

  initParticles() {
    this.particleCount = 800;
    const pos = new Float32Array(this.particleCount * 3);
    this.particleVel = new Float32Array(this.particleCount * 3);
    for (let i = 0; i < this.particleCount; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 40;
      pos[i * 3 + 1] = Math.random() * 18;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 40;
      this.particleVel[i * 3] = (Math.random() - 0.5) * 0.4;
      this.particleVel[i * 3 + 1] = (Math.random() - 0.5) * 0.4;
      this.particleVel[i * 3 + 2] = (Math.random() - 0.5) * 0.4;
    }
    this.particleGeo = new THREE.BufferGeometry();
    this.particleGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.particleMat = new THREE.PointsMaterial({ size: 0.16, color: 0xffffff, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false });
    this.particles = new THREE.Points(this.particleGeo, this.particleMat);
    this.scene.add(this.particles);
  }

  initInteractions() {
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    this.canvas.addEventListener('pointerdown', (e) => {
      pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
      pointer.y = -(e.clientY / window.innerHeight) * 2 + 1;
      raycaster.setFromCamera(pointer, this.camera);
      const hits = raycaster.intersectObjects(this.fragments, false);
      if (!hits.length) return;
      const hit = hits[0].object;
      // 主动叩问：触碰景观高光，文字才缓慢溶解浮现
      if (hit.userData && hit.userData.observer) {
        if (!aiMuted) showObserver(hit.userData.line);
        return;
      }
      if (hit.userData && hit.userData.text) showObserver(hit.userData.text);
    });
  }

  applyTerrain(type, tension) {
    const pos = this.surfaceGeo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i);
      pos.setZ(i, terrainHeight(x, y, type, tension));
    }
    pos.needsUpdate = true;
    this.surfaceGeo.computeVertexNormals();
  }

  setSignature(mood) {
    if (this.signature) this.islandGroup.remove(this.signature);
    const g = new THREE.Group();
    this.signature = g;
    this.islandGroup.add(g);

    if (mood === 'lonely') {
      const glow = new THREE.Mesh(
        new THREE.SphereGeometry(0.5, 24, 24),
        new THREE.MeshStandardMaterial({ color: 0xffc46b, emissive: 0xffa94d, emissiveIntensity: 2.5 })
      );
      glow.position.set(0, 2.8, 0);
      g.add(glow);
      const light = new THREE.PointLight(0xffc46b, 6, 14, 2);
      light.position.set(0, 3, 0);
      g.add(light);
    } else if (mood === 'calm') {
      for (let i = 0; i < 5; i++) {
        const j = new THREE.Mesh(
          new THREE.SphereGeometry(0.35, 16, 16),
          new THREE.MeshStandardMaterial({ color: 0x9ff5e6, emissive: 0x7ee8d2, emissiveIntensity: 1.6, transparent: true, opacity: 0.75 })
        );
        const by = 2 + Math.random() * 3;
        j.position.set((Math.random() - 0.5) * 10, by, (Math.random() - 0.5) * 10);
        j.userData = { phase: Math.random() * Math.PI * 2, base: by };
        g.add(j);
      }
    } else if (mood === 'anxious') {
      for (let i = 0; i < 7; i++) {
        const c = new THREE.Mesh(
          new THREE.OctahedronGeometry(0.4 + Math.random() * 0.4, 0),
          new THREE.MeshStandardMaterial({ color: 0x9fb3d1, emissive: 0x6b8fbf, emissiveIntensity: 1.0, flatShading: true })
        );
        c.position.set((Math.random() - 0.5) * 14, 0.5 + Math.random() * 2.5, (Math.random() - 0.5) * 14);
        c.rotation.set(Math.random(), Math.random(), Math.random());
        g.add(c);
      }
    } else if (mood === 'happy') {
      for (let i = 0; i < 8; i++) {
        const f = new THREE.Mesh(
          new THREE.SphereGeometry(0.22, 10, 10),
          new THREE.MeshStandardMaterial({ color: 0xffd9a0, emissive: 0xffb86b, emissiveIntensity: 1.6 })
        );
        f.position.set((Math.random() - 0.5) * 12, 0.6, (Math.random() - 0.5) * 12);
        f.userData = { phase: Math.random() * Math.PI * 2, base: 0.6 };
        g.add(f);
      }
    }
  }

  spawnFragment(text, color) {
    const frag = new THREE.Mesh(
      new THREE.OctahedronGeometry(0.35, 0),
      new THREE.MeshStandardMaterial({ color: color, emissive: color, emissiveIntensity: 0.6, transparent: true, opacity: 0.85, flatShading: true })
    );
    frag.position.set((Math.random() - 0.5) * 14, 1.5 + Math.random() * 3, (Math.random() - 0.5) * 14);
    frag.userData = { text: text, phase: Math.random() * Math.PI * 2, base: frag.position.y };
    this.islandGroup.add(frag);
    this.fragments.push(frag);
    if (this.fragments.length > 24) {
      const old = this.fragments.shift();
      if (old === this.highlight) this.highlight = null;
      this.islandGroup.remove(old);
    }
  }

  updateVisuals(params) {
    this.current = params;
    const p = params.palette || PALETTES.neutral;
    const c0 = new THREE.Color(p[0]);
    const c1 = new THREE.Color(p[1] || p[0]);

    this.scene.background = c1.clone().multiplyScalar(0.55);
    this.scene.fog.color.copy(c1).multiplyScalar(0.5);
    this.scene.fog.density = 0.012 + (1 - (params.clarity != null ? params.clarity : 0.5)) * 0.02;
    this.surfaceMat.color.set(c0);
    this.rock.material.color.set(c1.clone().multiplyScalar(0.35));

    this.applyTerrain(params.terrain || 'flat', params.tension != null ? params.tension : 0.5);
    this.setSignature(params.mood || 'neutral');

    this.particleMat.color.set(c0);
    this.particleType = params.particles || 'mist';
    this.particleEnergy = params.energy != null ? params.energy : 0.5;

    this.ambient.intensity = 0.35 + (params.clarity != null ? params.clarity : 0.5) * 0.7;

    if (params.text) this.spawnFragment(params.text, c0);
    syncLens(params);
    // AI 默认沉默：不弹话，只在景观上留下一处可触摸的高光
    this.offerObserverHighlight(params.mood || 'neutral', c0);
  }

  /** 在景观元素表面浮现可触摸玻璃高光；触碰后文字才缓慢溶解浮现。 */
  offerObserverHighlight(mood, color) {
    if (this.highlight) {
      this.islandGroup.remove(this.highlight);
      this.highlight = null;
    }
    if (aiMuted) return;  // 永久不回应：连高光也不出现

    const mat = new THREE.MeshStandardMaterial({
      color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.5,
      transparent: true, opacity: 0, roughness: 0.1, metalness: 0.0,
    });
    const glint = new THREE.Mesh(new THREE.SphereGeometry(0.42, 20, 20), mat);
    const a = Math.random() * Math.PI * 2;
    const r = 4 + Math.random() * 4;
    glint.position.set(Math.cos(a) * r, 2.2 + Math.random() * 1.6, Math.sin(a) * r);
    glint.userData = {
      observer: true,
      line: OBSERVER_LINES[mood] || OBSERVER_LINES.neutral,
      phase: Math.random() * Math.PI * 2,
      base: glint.position.y,
    };
    this.islandGroup.add(glint);
    this.highlight = glint;
    this.fragments.push(glint);  // 复用既有的 raycast 拾取
  }

  burst() {
    const geo = new THREE.BufferGeometry();
    const n = 600;
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n * 3; i++) pos[i] = (Math.random() - 0.5) * 2;
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({ size: 0.35, color: 0xff7a4d, transparent: true, opacity: 1, blending: THREE.AdditiveBlending, depthWrite: false });
    const pts = new THREE.Points(geo, mat);
    pts.position.set(0, 1, 0);
    this.scene.add(pts);
    const start = performance.now();
    const step = () => {
      const el = (performance.now() - start) / 1000;
      const arr = geo.attributes.position.array;
      for (let i = 0; i < n; i++) {
        arr[i * 3] *= 1.06;
        arr[i * 3 + 1] += 0.04;
        arr[i * 3 + 2] *= 1.06;
      }
      geo.attributes.position.needsUpdate = true;
      mat.opacity = Math.max(0, 1 - el * 1.4);
      if (el < 1.4) requestAnimationFrame(step);
      else this.scene.remove(pts);
    };
    step();
    this.sun.intensity = 4;
    setTimeout(() => { this.sun.intensity = 1.2; }, 300);
  }

  animateParticles(time) {
    const pos = this.particleGeo.attributes.position;
    const type = this.particleType;
    const e = this.particleEnergy;
    for (let i = 0; i < this.particleCount; i++) {
      let x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      if (type === 'rain') {
        y -= 0.14 * e;
        if (y < 0) { y = 18; x = (Math.random() - 0.5) * 40; z = (Math.random() - 0.5) * 40; }
      } else if (type === 'bubbles') {
        y += 0.08 * e;
        x += Math.sin(time * 2 + i) * 0.01;
        if (y > 18) { y = 0; x = (Math.random() - 0.5) * 30; z = (Math.random() - 0.5) * 30; }
      } else if (type === 'sparks') {
        x += this.particleVel[i * 3] * e * 3;
        y += this.particleVel[i * 3 + 1] * e * 3;
        z += this.particleVel[i * 3 + 2] * e * 3;
        if (Math.abs(x) > 20 || Math.abs(z) > 20 || y < 0 || y > 18) { x = (Math.random() - 0.5) * 30; y = Math.random() * 14; z = (Math.random() - 0.5) * 30; }
      } else if (type === 'stars') {
        // twinkle in place
      } else {
        x += this.particleVel[i * 3] * 0.3;
        y += Math.sin(time + i) * 0.02;
        z += this.particleVel[i * 3 + 2] * 0.3;
        if (Math.abs(x) > 20) this.particleVel[i * 3] *= -1;
        if (Math.abs(z) > 20) this.particleVel[i * 3 + 2] *= -1;
        if (y < 0) y = 16; if (y > 18) y = 0;
      }
      pos.setXYZ(i, x, y, z);
    }
    pos.needsUpdate = true;
    if (type === 'stars') this.particleMat.opacity = 0.5 + Math.sin(time * 2) * 0.3;
    else this.particleMat.opacity = 0.8;
  }

  onResize() {
    this.camera.aspect = window.innerWidth / window.innerHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(window.innerWidth, window.innerHeight);
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    const dt = this.clock.getDelta();
    const time = this.clock.elapsedTime;
    this.animateParticles(time);

    if (this.signature) {
      this.signature.children.forEach((ch) => {
        if (ch.userData && ch.userData.phase != null) {
          ch.position.y = (ch.userData.base != null ? ch.userData.base : ch.position.y) + Math.sin(time * 0.8 + ch.userData.phase) * 0.25;
        }
      });
    }
    this.fragments.forEach((frag) => {
      frag.position.y = frag.userData.base + Math.sin(time + frag.userData.phase) * 0.12;
      frag.rotation.y += 0.01;
    });

    // 观察者高光：缓慢呼吸，像光学浓度，而不是提示红点
    if (this.highlight && !aiMuted) {
      const breath = 0.18 + (Math.sin(time * 0.7 + this.highlight.userData.phase) * 0.5 + 0.5) * 0.34;
      this.highlight.material.opacity = breath;
      this.highlight.material.emissiveIntensity = 0.3 + breath;
    } else if (this.highlight) {
      this.highlight.material.opacity = 0;
    }

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}

// --- 透镜 / 观察者 / 状态 ----------------------------------------------------
function syncLens(params) {
  const t = params.tension != null ? params.tension : 0.5;
  document.documentElement.style.setProperty('--tension', String(t));
  const lens = document.getElementById('lens');
  // 平静时控件近乎消失；剧烈波动时折射升高、边缘色散
  lens.classList.toggle('stormy', t > 0.65);
  lens.classList.toggle('serene', t < 0.3);
}

let observerTimer = null;
function showObserver(text) {
  const el = document.getElementById('observer');
  const textEl = document.getElementById('observer-text');
  clearTimeout(observerTimer);
  if (!text || aiMuted) {
    el.classList.remove('shown');
    setTimeout(() => el.classList.add('hidden'), 1800);
    return;
  }
  textEl.textContent = text;
  el.classList.remove('hidden');
  requestAnimationFrame(() => el.classList.add('shown'));
  observerTimer = setTimeout(() => {
    el.classList.remove('shown');
    setTimeout(() => el.classList.add('hidden'), 1800);
  }, 9000);
}

function setStatus(text) {
  const el = document.getElementById('status');
  if (text) { el.textContent = text; el.classList.add('visible'); }
  else el.classList.remove('visible');
}

// --- 应用启动 ----------------------------------------------------------------
const canvas = document.getElementById('island');
const renderer = new IslandRenderer(canvas);
// 调试句柄：供自动化验证读取渲染状态，不参与业务逻辑
if (typeof window !== 'undefined') window.__moodscape = { renderer, get aiMuted() { return aiMuted; } };
let currentIslandId = null;
let idleTimer = null;

function setLensIdle(idle) {
  const lens = document.getElementById('lens');
  if (idle) lens.classList.add('idle');
  else lens.classList.remove('idle');
}

function touchInput() {
  setLensIdle(false);
  lastActivity = Date.now();
  presenceLevel = 1.0;
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => setLensIdle(true), 20000);
}

async function send() {
  const input = document.getElementById('mood-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  const membrane = document.getElementById('input-membrane');
  membrane.classList.add('dissolving');
  setStatus('…');
  let params;
  try {
    const r = await fetch(API + '/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: CURRENT_USER, text: text, theme: currentTheme }),
    });
    const d = await r.json();
    currentIslandId = d.id;
    params = d.visual_params;
    renderer.updateVisuals(Object.assign({}, params, { text: text }));
    // 不回显情绪标签：变化发生在岛屿本身，不是一个被打分的结论
    setStatus('');
  } catch (err) {
    params = mockParams(text);
    renderer.updateVisuals(Object.assign({}, params, { text: text }));
    setStatus('离线');
  }
  setTimeout(() => membrane.classList.remove('dissolving'), 700);
  touchInput();
}

document.getElementById('send-btn').addEventListener('click', send);
document.getElementById('mood-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  touchInput();
});

document.getElementById('observer').addEventListener('click', () => {
  const el = document.getElementById('observer');
  el.classList.remove('shown');
  setTimeout(() => el.classList.add('hidden'), 1200);
});

// 情绪清理：长按释放（无进度条，按住停留至微光升起）
(function setupRelease() {
  const btn = document.getElementById('release-btn');
  let timer = null;
  const start = () => {
    btn.classList.add('charging');
    timer = setTimeout(() => {
      btn.classList.add('charged');
      renderer.burst();
      if (currentIslandId != null && renderer.current) {
        const emotion = renderer.current.mood || 'anxious';
        fetch(API + '/release', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ island_id: currentIslandId, emotion: emotion }),
        }).then((r) => r.json())
          .then((d) => setStatus('已释放，转化为 ' + d.resource))
          .catch(() => setStatus('情绪已释放，化作岛屿资源。'));
      } else {
        setStatus('情绪已释放，化作岛屿资源。');
      }
    }, 900);
  };
  const end = () => {
    btn.classList.remove('charging', 'charged');
    if (timer) clearTimeout(timer);
    timer = null;
    touchInput();
  };
  btn.addEventListener('pointerdown', start);
  btn.addEventListener('pointerup', end);
  btn.addEventListener('pointerleave', end);
  btn.addEventListener('pointercancel', end);
})();

touchInput();

// ============================================================
//  材质 / 订阅 / 语音 / 歌曲 / 社交 / 打印
// ============================================================

// --- 材质菜单 + 订阅 -------------------------------------------------
const materialBtn = document.getElementById('material-btn');
const materialMenu = document.getElementById('material-menu');
materialBtn.addEventListener('click', () => materialMenu.classList.toggle('hidden'));
document.querySelectorAll('.material-option').forEach((opt) => {
  opt.addEventListener('click', () => {
    currentTheme = opt.getAttribute('data-theme') || null;
    document.querySelectorAll('.material-option').forEach((o) => o.classList.remove('selected'));
    opt.classList.add('selected');
    materialMenu.classList.add('hidden');
    setStatus('材质：' + (currentTheme ? opt.textContent : '原生'));
    touchInput();
  });
});
document.getElementById('subscribe-btn').addEventListener('click', async () => {
  const mats = currentTheme ? [currentTheme] : [];
  try {
    const r = await fetch(API + '/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: CURRENT_USER, tier: 'companion', materials: mats }),
    });
    await r.json();
    document.getElementById('entitlements').textContent = '同伴 · 双岛 / 材质已解锁';
    setStatus('已升级同伴订阅');
  } catch (err) { setStatus('订阅失败（后端未连接）'); }
});

// --- 语音 / 歌曲输入 ---------------------------------------------------
async function analyzeAudio(endpoint, blob, filename) {
  setStatus('…');
  const membrane = document.getElementById('input-membrane');
  membrane.classList.add('dissolving');
  const fd = new FormData();
  fd.append('file', blob, filename);
  fd.append('user_id', String(CURRENT_USER));
  try {
    const r = await fetch(API + endpoint, { method: 'POST', body: fd });
    const d = await r.json();
    renderer.updateVisuals(Object.assign({}, d.visual_params, { text: d.text }));
    setStatus('');
  } catch (err) {
    const p = mockParams(filename);
    renderer.updateVisuals(Object.assign({}, p, { text: '' }));
    setStatus('离线');
  }
  setTimeout(() => membrane.classList.remove('dissolving'), 700);
  touchInput();
}

const micBtn = document.getElementById('mic-btn');
micBtn.addEventListener('click', async () => {
  if (mediaRecorder && mediaRecorder.state === 'recording') { mediaRecorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = (e) => { if (e.data.size) audioChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      micBtn.classList.remove('recording');
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
      await analyzeAudio('/analyze/voice', blob, 'voice.webm');
    };
    mediaRecorder.start();
    micBtn.classList.add('recording');
    touchInput();
  } catch (err) { setStatus('无法访问麦克风'); }
});

const songBtn = document.getElementById('song-btn');
const songFile = document.getElementById('song-file');
songBtn.addEventListener('click', () => songFile.click());
songFile.addEventListener('change', () => {
  const f = songFile.files[0];
  if (f) analyzeAudio('/analyze/song', f, f.name);
  songFile.value = '';
});

// --- 社交：静默陪伴 -----------------------------------------------------
function updatePartnerPresence(level) {
  const el = document.getElementById('presence');
  const dot = document.getElementById('presence-dot');
  if (level > 0.2) {
    el.classList.remove('hidden');
    dot.style.opacity = String(0.3 + level * 0.7);
    dot.style.transform = 'scale(' + (0.7 + level * 0.8).toFixed(2) + ')';
  } else {
    dot.style.opacity = '0.15';
  }
}

function connectPresence() {
  let ws;
  const wsBase = API.replace(/^http/, 'ws');
  try { ws = new WebSocket(wsBase + '/ws/' + CURRENT_USER); } catch (e) { return; }
  ws.onopen = () => {
    presenceSocket = ws;
    sendPresence();
  };
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch (err) { return; }
    if (msg.type === 'presence' && msg.data && msg.data.type === 'presence') {
      updatePartnerPresence(msg.data.level);
    }
  };
  ws.onclose = () => { presenceSocket = null; setTimeout(connectPresence, 5000); };
}

function sendPresence() {
  if (!presenceSocket || presenceSocket.readyState !== WebSocket.OPEN) return;
  try { presenceSocket.send(JSON.stringify({ type: 'presence', level: presenceLevel })); } catch (err) {}
}

setInterval(() => {
  const idleMin = (Date.now() - lastActivity) / 60000;
  // 静默不等于离开：浓度缓慢退到 0.35，保留"还在"的底色
  presenceLevel = Math.max(0.35, 1 - idleMin * 0.18);
  if (document.hidden) presenceLevel = Math.min(presenceLevel, 0.4);
  sendPresence();
}, 8000);

async function pollBridge() {
  if (!bondId) return;
  try {
    const r = await fetch(API + '/bond/' + bondId + '/bridge');
    const d = await r.json();
    const btn = document.getElementById('bridge-state');
    btn.classList.remove('hidden');
    // 桥墩 -> 预流 -> 凝固：三态都只靠光学浓度表达，不催促
    btn.classList.toggle('pier', d.bridge === 'pier');
    btn.classList.toggle('flowing', d.bridge === 'liquid');
    btn.classList.toggle('active', d.bridge === 'frozen');
    btn.setAttribute('aria-label',
      d.bridge === 'pier' ? '桥墩已立，等待对方回应'
      : d.bridge === 'liquid' ? '液态玻璃预流中'
      : '桥已凝固');
  } catch (err) {}
}

document.getElementById('bond-btn').addEventListener('click', async () => {
  try {
    const r = await fetch(API + '/bond', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_a: CURRENT_USER, user_b: PARTNER_ID }) });
    const d = await r.json();
    bondId = d.id;
    // 付费仪式化为桥墩出现；对方主动"回应"后桥才生成，不代替对方点头
    setStatus(d.status === 'active' ? '' : '桥墩已立');
    pollBridge();
  } catch (err) { setStatus('未连接'); }
});

// 受邀方本人回应：长按「连」接受邀请，桥才开始预流
(function setupBondRespond() {
  const btn = document.getElementById('bond-btn');
  let timer = null;
  const start = () => {
    timer = setTimeout(async () => {
      try {
        const r = await fetch(API + '/bond/invites/' + CURRENT_USER);
        const invites = await r.json();
        if (!invites.length) return;
        await fetch(API + '/bond/' + invites[0].id + '/respond?user_id=' + CURRENT_USER, { method: 'POST' });
        bondId = invites[0].id;
        pollBridge();
      } catch (err) {}
    }, 900);
  };
  const end = () => { if (timer) clearTimeout(timer); timer = null; };
  btn.addEventListener('pointerdown', start);
  btn.addEventListener('pointerup', end);
  btn.addEventListener('pointerleave', end);
  btn.addEventListener('pointercancel', end);
})();

function showBottle(b) {
  const layer = document.getElementById('bottle-layer');
  if (layer.querySelector('.bottle-orb')) return;
  const orb = document.createElement('button');
  orb.className = 'bottle-orb';
  // 悬浮液态玻璃球：不写情绪标签，氛围由内部光色透出
  orb.setAttribute('aria-label', '有人递来一片景观');
  const tint = (b.snippet && b.snippet.palette && b.snippet.palette[0]) || '#9fd8ff';
  orb.style.setProperty('--orb-tint', tint);
  orb.addEventListener('click', async () => {
    orb.classList.add('opening');
    try { await fetch(API + '/bottle/' + b.id + '/open?user_id=' + CURRENT_USER, { method: 'POST' }); } catch (err) {}
    // 对方景观以薄光学叠加短暂浮现，随后退去，自己的岛不被替换
    overlayForeignScape(b.snippet || {});
    setTimeout(() => orb.remove(), 700);
  });
  layer.appendChild(orb);
  setTimeout(() => { if (orb.isConnected) orb.remove(); }, 60000);
}

/** 漂流瓶 2.0：对方景观薄光学叠加短暂浮现并退去，不覆盖自己的岛。 */
function overlayForeignScape(snippet) {
  const mine = renderer.current ? Object.assign({}, renderer.current) : null;
  renderer.updateVisuals(Object.assign({}, snippet, { text: '' }));
  const veil = document.getElementById('scape-veil');
  if (veil) {
    const tint = (snippet.palette && snippet.palette[0]) || '#9fd8ff';
    veil.style.background = 'radial-gradient(circle at 50% 45%, ' + tint + '22, transparent 70%)';
    veil.classList.add('shown');
    setTimeout(() => veil.classList.remove('shown'), 7000);
  }
  // 退去：回到自己的岛
  setTimeout(() => { if (mine) renderer.updateVisuals(mine); }, 7600);
}

async function pollBottles() {
  try {
    const r = await fetch(API + '/bottle/' + CURRENT_USER);
    const list = await r.json();
    if (list && list.length) showBottle(list[0]);
  } catch (err) {}
}

document.getElementById('bottle-send-btn').addEventListener('click', async () => {
  const params = renderer.current || mockParams('');
  try {
    await fetch(API + '/bottle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sender_id: CURRENT_USER, island_id: currentIslandId || 0, ambience: params.mood, snippet: params }) });
    setStatus('漂流瓶已放入岛缘水面');
  } catch (err) { setStatus('漂流瓶投放失败'); }
});

function spawnLight() {
  const light = new THREE.PointLight(0xffe8a0, 9, 12, 2);
  light.position.set(0, 2.2, 0);
  renderer.scene.add(light);
  const glow = new THREE.Mesh(new THREE.SphereGeometry(0.45, 16, 16), new THREE.MeshStandardMaterial({ color: 0xffe8a0, emissive: 0xffd070, emissiveIntensity: 3 }));
  glow.position.copy(light.position);
  renderer.scene.add(glow);
  setTimeout(() => { light.intensity = 1; glow.scale.setScalar(0.4); }, 2500);
  setTimeout(() => { renderer.scene.remove(light); renderer.scene.remove(glow); }, 6000);
}

function spawnFlower() {
  const flower = new THREE.Mesh(new THREE.SphereGeometry(0.3, 12, 12), new THREE.MeshStandardMaterial({ color: 0xffb8c8, emissive: 0xff88a8, emissiveIntensity: 1.6 }));
  flower.position.set((Math.random() - 0.5) * 6, 0.6, (Math.random() - 0.5) * 6);
  renderer.scene.add(flower);
  setTimeout(() => renderer.scene.remove(flower), 8000);
}

async function doAction(kind) {
  if (kind === 'light') spawnLight(); else spawnFlower();
  if (bondId) {
    try { await fetch(API + '/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ bond_id: bondId, actor_id: CURRENT_USER, kind: kind }) }); } catch (err) {}
  }
}

/** 凝胶弹性：点灯 / 种花需按住停留至微光升起，不显示进度条。 */
function setupHoldAction(btnId, kind) {
  const btn = document.getElementById(btnId);
  let timer = null;
  const start = () => {
    btn.classList.add('holding');
    timer = setTimeout(() => {
      btn.classList.add('risen');
      doAction(kind);
      setTimeout(() => btn.classList.remove('risen'), 900);
    }, 850);
  };
  const end = () => {
    btn.classList.remove('holding');
    if (timer) clearTimeout(timer);
    timer = null;
  };
  btn.addEventListener('pointerdown', start);
  btn.addEventListener('pointerup', end);
  btn.addEventListener('pointerleave', end);
  btn.addEventListener('pointercancel', end);
}
setupHoldAction('light-btn', 'light');
setupHoldAction('flower-btn', 'flower');

// --- 情绪藏品 / 实体打印 -------------------------------------------------
function showTree(svg) {
  const layer = document.getElementById('bottle-layer');
  const card = document.createElement('div');
  card.style.cssText = 'pointer-events:auto;background:rgba(10,10,18,0.62);border:1px solid rgba(255,255,255,0.2);border-radius:22px;padding:14px;backdrop-filter:blur(16px);max-width:420px;box-shadow:0 8px 32px rgba(0,0,0,0.4);';
  card.innerHTML = svg;
  card.addEventListener('click', () => card.remove());
  layer.appendChild(card);
  setTimeout(() => { if (card.isConnected) card.remove(); }, 10000);
}

document.getElementById('print-btn').addEventListener('click', async () => {
  if (!currentIslandId) { setStatus('先生成一座岛屿'); return; }
  try {
    let r = await fetch(API + '/seed', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: CURRENT_USER, island_id: currentIslandId, label: '纪念树 · ' + (renderer.current ? renderer.current.mood : 'neutral') }) });
    let seed = await r.json();
    r = await fetch(API + '/print', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: CURRENT_USER, seed_id: seed.id }) });
    let order = await r.json();
    setStatus('纪念树已下单打印 (订单#' + order.id + ')');
    if (order.tree_svg) showTree(order.tree_svg);
  } catch (err) { setStatus('打印下单失败（后端未连接）'); }
});

// --- 信息呼吸：日常态几乎不存在，社交态才升起最少必要控件 ----------------
(function setupSocialBreath() {
  const lens = document.getElementById('social-lens');
  const toggle = document.getElementById('social-toggle');
  let foldTimer = null;
  const fold = () => { lens.classList.add('folded'); clearTimeout(foldTimer); };
  const unfold = () => {
    lens.classList.remove('folded');
    clearTimeout(foldTimer);
    // 社交态自行退去，不靠用户关闭
    foldTimer = setTimeout(fold, 30000);
  };
  toggle.addEventListener('click', () => {
    if (lens.classList.contains('folded')) unfold(); else fold();
    touchInput();
  });
  // 社交态内任何操作都延长停留
  document.getElementById('social-controls').addEventListener('pointerdown', unfold);
})();

// --- 沉默被完整支持：AI 可被永久不回应 -----------------------------------
(function setupSilence() {
  const btn = document.getElementById('silence-btn');
  const sync = () => {
    btn.textContent = aiMuted ? '已沉默' : '保持沉默';
    btn.classList.toggle('selected', aiMuted);
  };
  sync();
  btn.addEventListener('click', () => {
    aiMuted = !aiMuted;
    localStorage.setItem('ms_ai_muted', aiMuted ? '1' : '0');
    if (aiMuted) {
      showObserver('');  // 立即收回已浮现的文字
      if (renderer.highlight) {
        renderer.islandGroup.remove(renderer.highlight);
        renderer.fragments = renderer.fragments.filter((f) => f !== renderer.highlight);
        renderer.highlight = null;
      }
    }
    sync();
    touchInput();
  });
})();

// --- 启动社交链路 -------------------------------------------------------
connectPresence();
pollBottles();
setInterval(pollBottles, 10000);
setInterval(pollBridge, 4000);

// --- 离线支持：注册 Service Worker --------------------------------------
if ('serviceWorker' in navigator && location.protocol !== 'file:') {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  });
}

