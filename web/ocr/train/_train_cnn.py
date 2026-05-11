"""Train a small CNN on Byzantine neume glyph crops. Exports weights as a flat JSON."""
import json, struct, time, sys, os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CELL = 48

# ── Load data ─────────────────────────────────────────────────────

with open(os.path.join(DATA_DIR, "meta.json")) as f:
    meta = json.load(f)

N = meta["totalSamples"]
C = meta["numClasses"]
print(f"{N} samples, {C} classes, {CELL}x{CELL}px")

xs_raw = np.fromfile(os.path.join(DATA_DIR, "xs.bin"), dtype=np.float32)
ys_raw = np.fromfile(os.path.join(DATA_DIR, "ys.bin"), dtype=np.float32)

xs = xs_raw.reshape(N, 1, CELL, CELL)
ys = ys_raw.reshape(N, C)

# Train/val split
indices = np.random.permutation(N)
split = int(N * 0.8)
train_idx, val_idx = indices[:split], indices[split:]

train_ds = TensorDataset(torch.tensor(xs[train_idx]), torch.tensor(ys[train_idx]))
val_ds = TensorDataset(torch.tensor(xs[val_idx]), torch.tensor(ys[val_idx]))
train_dl = DataLoader(train_ds, batch_size=64, shuffle=True)
val_dl = DataLoader(val_ds, batch_size=64)

# ── Model ──────────────────────────────────────────────────────────

class GlyphCNN(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(128, 192, 3, padding=1), nn.ReLU(),
        )
        self.gap = nn.AdaptiveAvgPool2d(1)
        self.dropout = nn.Dropout(0.4)
        self.fc = nn.Linear(192, num_classes)

    def forward(self, x):
        x = self.conv(x)
        x = self.gap(x).flatten(1)
        x = self.dropout(x)
        return self.fc(x)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}")

model = GlyphCNN(C).to(device)
opt = optim.Adam(model.parameters(), lr=0.002)
scheduler = optim.lr_scheduler.CosineAnnealingLR(opt, T_max=60)
loss_fn = nn.CrossEntropyLoss()

# ── Train ──────────────────────────────────────────────────────────

epochs = 60
best_acc = 0
start = time.time()

for epoch in range(epochs):
    model.train()
    train_loss, train_correct, train_total = 0, 0, 0
    for xb, yb in train_dl:
        xb, yb = xb.to(device), yb.to(device)
        opt.zero_grad()
        logits = model(xb)
        loss = loss_fn(logits, yb)
        loss.backward()
        opt.step()
        train_loss += loss.item() * xb.size(0)
        train_correct += (logits.argmax(1) == yb.argmax(1)).sum().item()
        train_total += xb.size(0)

    model.eval()
    val_correct, val_total = 0, 0
    with torch.no_grad():
        for xb, yb in val_dl:
            xb, yb = xb.to(device), yb.to(device)
            logits = model(xb)
            val_correct += (logits.argmax(1) == yb.argmax(1)).sum().item()
            val_total += xb.size(0)

    train_acc = train_correct / train_total * 100
    val_acc = val_correct / val_total * 100
    print(f"  epoch {epoch+1:2d}  train_acc={train_acc:.1f}%  val_acc={val_acc:.1f}%  loss={train_loss/train_total:.3f}")

    if val_acc > best_acc:
        best_acc = val_acc
    scheduler.step()

elapsed = time.time() - start
print(f"\nBest val accuracy: {best_acc:.1f}%  ({elapsed:.0f}s)")

# ── Export weights as JSON ─────────────────────────────────────────

weights = {}
for name, param in model.state_dict().items():
    weights[name] = param.cpu().numpy().tolist()

out_dir = os.path.join(os.path.dirname(__file__), "chant_cnn_model")
os.makedirs(out_dir, exist_ok=True)

with open(os.path.join(out_dir, "weights.json"), "w") as f:
    json.dump({"weights": weights, "classes": meta["classes"], "cellSize": CELL}, f)

print(f"\nExported to {out_dir}/weights.json")
print(f"Classes: {len(meta['classes'])}")
