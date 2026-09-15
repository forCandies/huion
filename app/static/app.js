document.querySelectorAll('[data-tab]').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach((item) => item.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    document.querySelector(`#tab-${button.dataset.tab}`).classList.add('active');
  });
});

document.querySelectorAll('.toggle-row').forEach((row) => {
  row.addEventListener('click', (event) => {
    if (event.target.tagName !== 'INPUT') row.querySelector('input').click();
  });
});

document.querySelectorAll('[data-copy]').forEach((button) => {
  button.addEventListener('click', async () => {
    await navigator.clipboard.writeText(button.dataset.copy);
    const original = button.textContent;
    button.textContent = 'Cesta zkopírována';
    setTimeout(() => { button.textContent = original; }, 1400);
  });
});
