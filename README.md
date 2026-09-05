# ⚡ PulseAPI — Real-Time API Uptime & Latency Monitoring SaaS Engine

<div align="center">

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](Dockerfile)
[![License MIT](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-100%25_Passing-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](tests/)

<p align="center">
  <b>Production-Grade High-Frequency API, Webhook & Server Monitoring SaaS platform with Instant Telegram Alerts & Cyberpunk Analytics Dashboard.</b>
</p>

</div>

---

## 🌟 Architecture & Core Features

- ⚡ **High-Frequency Async Probing:** Powered by `httpx` async workers with sub-10ms probe overhead.
- 🚨 **Multi-Channel Alert Dispatch:** Instant incident alerts & recovery notices sent to Telegram groups / webhooks.
- 📊 **Real-Time Latency Visualization:** Interactive Chart.js graphs mapping time-to-first-byte (TTFB) streams.
- 🌐 **Public Status Page Generator:** Transparent system status dashboard for external customers.
- 🔒 **Zero-Config SQLite Storage:** WAL-mode SQLite database with automatic incident tracking and 50-probe rolling SLA calculation.
- 🐳 **Dockerized Deployment:** Ready for 1-click launch on any VPS or Cloud Run cluster.

---

## 🚀 Quickstart

### 1. Run via Python / FastAPI:
```bash
cd server
pip install -r requirements.txt
uvicorn server.main:app --reload --port 8000
```

### 2. Run via Docker Compose:
```bash
docker-compose up -d --build
```

### 3. Open Interactive Dashboard:
Open `client/index.html` or deploy directly to Vercel/Netlify!

---

## 🧪 Automated Testing

Run the test suite with `pytest`:
```bash
pytest -v tests/
```

---

## 👨‍💻 Author

**Javohirbek Asqarov (Jasper)**
- GitHub: [@salomh46-rgb](https://github.com/salomh46-rgb)
- Portfolio: [javohirbek-portfolio.vercel.app](https://javohirbek-portfolio.vercel.app/)
- Telegram: [@Dr_eviluz](https://t.me/Dr_eviluz)
- Email: [salomh46@gmail.com](mailto:salomh46@gmail.com)

---

## 📄 License
MIT © [Javohirbek Asqarov](LICENSE)
