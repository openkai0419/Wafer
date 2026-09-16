export function debounce(delayMs, fn) {
  let timer = null;
  let pending = null;

  const fire = () => {
    const args = pending || [];
    timer = null;
    pending = null;
    fn(...args);
  };

  const wrapper = (...args) => {
    pending = args;
    clearTimeout(timer);
    timer = setTimeout(fire, delayMs);
  };

  wrapper.flush = () => {
    clearTimeout(timer);
    fire();
  };

  wrapper.cancel = () => {
    clearTimeout(timer);
    timer = null;
    pending = null;
  };

  return wrapper;
}
