# MAFS 5360 Group 1 Exchange Simulator

## Group Members

- LIM, Hyungmin (group leader)
- JITENDRA JAIN, Jai
- KONG, Lington

## Environment Setup (Python 3.13)

Use Python **3.13.x** (latest patch version is fine).

### Option 1: `venv`

```bash
python3.13 --version
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Option 2: `conda`

```bash
conda create -n exchange-simulator python=3.13 -y
conda activate exchange-simulator
python -m pip install --upgrade pip
pip install -r requirements.txt
```