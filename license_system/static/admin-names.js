/* Suggestions only. The authority chooses and validates the final name. */
(() => {
  function suggest(customer) {
    if (!customer.trim()) return '';
    const plain = customer.toLowerCase().replace(/đ/g, 'd').normalize('NFD');
    const suffix = plain.replace(/[^a-z0-9]/g, '') || 'khachhang';
    return 'quantri-' + suffix.slice(0, 56);
  }

  document.querySelectorAll('form[data-admin-naming]').forEach(form => {
    const customer = form.querySelector('[name="customer"]');
    const username = form.querySelector('[name="admin_username"]');
    const auto = form.querySelector('[name="admin_username_auto"]');
    let automatic = !username.value;
    function update() {
      if (automatic) {
        username.value = suggest(customer ? customer.value : form.dataset.customer);
        auto.value = '1';
      }
    }
    username.addEventListener('input', () => {
      automatic = !username.value.trim();
      auto.value = automatic ? '1' : '0';
    });
    username.addEventListener('blur', update);
    if (customer) customer.addEventListener('input', update);
    update();
  });
})();
