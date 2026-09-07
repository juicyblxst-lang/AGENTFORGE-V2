(() => {
  const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (!isMobile) return;

  const hasProvider = () => Boolean(window.ethereum);

  const openInMetaMask = () => {
    const target = `${window.location.host}${window.location.pathname}${window.location.search.replace(/([?&])mm_connect=1(&|$)/, '$1').replace(/[?&]$/, '')}`;
    const separator = target.includes('?') ? '&' : '?';
    const url = `https://metamask.app.link/dapp/${target}${separator}mm_connect=1`;
    window.location.href = url;
  };

  document.addEventListener('click', (event) => {
    if (hasProvider()) return;
    const target = event.target instanceof Element ? event.target.closest('button.wallet') : null;
    if (!target) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    openInMetaMask();
  }, true);

  // When MetaMask opens the dapp through the deep link, finish the connection
  // automatically once the injected provider and React button are available.
  if (new URLSearchParams(window.location.search).get('mm_connect') === '1') {
    const started = Date.now();
    const timer = window.setInterval(() => {
      const button = document.querySelector('button.wallet');
      if (hasProvider() && button) {
        window.clearInterval(timer);
        history.replaceState({}, '', `${window.location.pathname}${window.location.search.replace(/([?&])mm_connect=1(&|$)/, '$1').replace(/[?&]$/, '')}${window.location.hash}`);
        button.click();
      } else if (Date.now() - started > 30000) {
        window.clearInterval(timer);
      }
    }, 250);
  }
})();
