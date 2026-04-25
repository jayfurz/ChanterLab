// PointerDrag — unified pointer-events drag-and-drop.
//
// Replaces HTML5 DataTransfer drag (which does not fire on iOS/iPadOS touch
// and on some Android setups). Uses pointerdown/pointermove/pointerup with
// setPointerCapture so mouse, pen, and touch all follow the same path.
//
// Usage:
//   makeDraggable(sourceEl, {
//     payload: () => ({ ... }),      // called at drag start
//     targetSelector: '#scale-ladder', // drop zone (closest match)
//     dropEvent: 'chanterlab:palette-drop', // default is this
//     clickEvent: 'chanterlab:palette-click', // optional click-without-drag event
//     ghost: () => Node,             // optional; defaults to cloning src
//   });
//
// On drop, dispatches a CustomEvent(dropEvent, { detail: { payload,
// clientX, clientY } }) on the closest matching target element.

const DRAG_THRESHOLD_PX = 6;

export function makeDraggable(src, opts) {
  const {
    payload,
    targetSelector,
    dropEvent = 'chanterlab:palette-drop',
    clickEvent = null,
    ghost: ghostFactory,
  } = opts;

  src.addEventListener('pointerdown', onDown);
  if (clickEvent) {
    src.addEventListener('keydown', onKeyDown);
  }

  function onKeyDown(e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    dispatchSourceEvent(clickEvent, src, payload(), null, null);
  }

  function onDown(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;

    const startX = e.clientX;
    const startY = e.clientY;
    const data = payload();
    let ghost = null;
    let dragging = false;
    let lastHoverTarget = null;

    src.setPointerCapture(e.pointerId);
    src.addEventListener('pointermove', onMove);
    src.addEventListener('pointerup', onUp);
    src.addEventListener('pointercancel', onCancel);

    function onMove(me) {
      if (!dragging) {
        const dx = me.clientX - startX;
        const dy = me.clientY - startY;
        if (dx * dx + dy * dy < DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX) return;
        dragging = true;
        ghost = makeGhost(ghostFactory, src);
        document.body.appendChild(ghost);
        positionGhost(ghost, me.clientX, me.clientY);
        src.classList.add('dragging');
      } else {
        positionGhost(ghost, me.clientX, me.clientY);
      }

      // Hover preview for drop target.
      if (dragging) {
        const hoverTarget = document.elementFromPoint(me.clientX, me.clientY);
        const zone = hoverTarget && hoverTarget.closest(targetSelector);
        if (zone !== lastHoverTarget) {
          if (lastHoverTarget) {
            lastHoverTarget.dispatchEvent(new CustomEvent('chanterlab:palette-hover', {
              detail: { payload: data, clientX: null, clientY: null, leaving: true },
            }));
          }
          lastHoverTarget = zone;
        }
        if (zone) {
          zone.dispatchEvent(new CustomEvent('chanterlab:palette-hover', {
            detail: { payload: data, clientX: me.clientX, clientY: me.clientY },
          }));
        }
      }
    }

    function onUp(ue) {
      const wasDragging = dragging;
      const upX = ue.clientX;
      const upY = ue.clientY;
      cleanup();
      if (!wasDragging) {
        dispatchSourceEvent(clickEvent, src, data, upX, upY);
        return;
      }
      const target = document.elementFromPoint(upX, upY);
      const zone = target && target.closest(targetSelector);
      if (!zone) return;
      zone.dispatchEvent(new CustomEvent(dropEvent, {
        detail: { payload: data, clientX: upX, clientY: upY },
      }));
    }

    function onCancel() { cleanup(); }

    function cleanup() {
      if (lastHoverTarget) {
        lastHoverTarget.dispatchEvent(new CustomEvent('chanterlab:palette-hover', {
          detail: { payload: data, clientX: null, clientY: null, leaving: true },
        }));
        lastHoverTarget = null;
      }
      src.removeEventListener('pointermove', onMove);
      src.removeEventListener('pointerup', onUp);
      src.removeEventListener('pointercancel', onCancel);
      if (src.hasPointerCapture(e.pointerId)) {
        src.releasePointerCapture(e.pointerId);
      }
      src.classList.remove('dragging');
      if (ghost && ghost.parentNode) ghost.parentNode.removeChild(ghost);
      ghost = null;
    }
  }
}

function dispatchSourceEvent(eventName, src, data, x, y) {
  if (!eventName) return;
  src.dispatchEvent(new CustomEvent(eventName, {
    bubbles: true,
    detail: { payload: data, clientX: x, clientY: y },
  }));
}

function makeGhost(factory, src) {
  const node = factory ? factory() : src.cloneNode(true);
  node.classList.add('pointer-drag-ghost');
  const rect = src.getBoundingClientRect();
  node.style.width  = rect.width  + 'px';
  node.style.height = rect.height + 'px';
  return node;
}

function positionGhost(node, x, y) {
  const w = parseFloat(node.style.width)  || 40;
  const h = parseFloat(node.style.height) || 40;
  // Sits above the pointer so the drop target remains visible under the finger.
  node.style.left = (x - w / 2) + 'px';
  node.style.top  = (y - h - 8) + 'px';
}
