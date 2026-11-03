/* V23: Pure client-side interactions; server-side login, CSRF and validation remain authoritative. */
(() => {
  'use strict';
  const form = document.getElementById('auth-form');
  if (!form) return;
  const mode = form.dataset.authMode;
  const password = document.getElementById('password');
  const confirm = document.getElementById('confirm');
  const capsHint = document.getElementById('caps-hint');
  const message = document.getElementById('form-message');
  const submit = document.getElementById('auth-submit');
  const strengthLabel = document.getElementById('password-strength');
  const strengthMeter = document.querySelector('.password-meter');
  const strengthBar = strengthMeter?.querySelector('.meter-track i');
  const confirmHint = document.getElementById('confirm-hint');

  for (const toggle of document.querySelectorAll('[data-reveal]')) {
    toggle.addEventListener('click', () => {
      const input = document.getElementById(toggle.dataset.reveal);
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      const label = toggle.querySelector('.reveal-label');
      if (label) label.textContent = show ? '隐藏' : '显示';
      const glyph = toggle.querySelector('svg');
      if (glyph && window.MarlIcons) glyph.outerHTML = window.MarlIcons.icon(show ? 'eye-off' : 'eye');
      toggle.setAttribute('aria-label', (show ? '隐藏' : '显示') + (input === confirm ? '确认密码' : '密码'));
      toggle.setAttribute('aria-pressed', String(show));
      input.focus({ preventScroll: true });
    });
  }
  if (password && capsHint) {
    const capsState = (event) => { capsHint.hidden = !(event.getModifierState && event.getModifierState('CapsLock')); };
    password.addEventListener('keydown', capsState);
    password.addEventListener('keyup', capsState);
    password.addEventListener('blur', () => { capsHint.hidden = true; });
  }

  const passwordFeedback = () => {
    if (mode !== 'register' || !password) return;
    const value = password.value;
    const hasLetter = /[A-Za-z\p{L}]/u.test(value);
    const hasDigit = /[0-9\p{N}]/u.test(value);
    const hasSymbol = /[^\p{L}\p{N}]/u.test(value);
    const ready = value.length >= 10 && value.length <= 128 && hasLetter && hasDigit;
    let level = 0;
    if (value.length) {
      level = ready ? (value.length >= 14 && hasSymbol ? 4 : value.length >= 12 || hasSymbol ? 3 : 2) : 1;
    }
    if (strengthMeter) strengthMeter.dataset.level = String(level);
    if (strengthBar) strengthBar.style.width = `${level * 25}%`;
    if (strengthLabel) strengthLabel.textContent = !value ? '请设置账户密码' : !ready ? '尚未满足密码要求' : level === 4 ? '符合要求 · 强度较高' : '符合密码要求';
    if (confirm?.value) confirmFeedback();
  };
  const confirmFeedback = () => {
    if (!confirm || !confirmHint || !password) return;
    const hasValue = confirm.value.length > 0;
    const equal = confirm.value === password.value;
    confirmHint.textContent = !hasValue ? '请与上方密码保持一致' : equal ? '两次密码一致' : '两次输入的密码不一致';
    confirmHint.classList.toggle('mismatch', hasValue && !equal);
    confirmHint.classList.toggle('match', hasValue && equal);
    // Native constraint validation gives accessible, focused feedback before submission.
    confirm.setCustomValidity(hasValue && !equal ? '两次输入的密码不一致' : '');
  };
  password?.addEventListener('input', () => { passwordFeedback(); if (message) message.hidden = true; });
  confirm?.addEventListener('input', confirmFeedback);

  form.addEventListener('submit', (event) => {
    if (mode === 'register' && password && confirm) {
      confirmFeedback();
      const hasLetter = /[A-Za-z\p{L}]/u.test(password.value);
      const hasDigit = /[0-9\p{N}]/u.test(password.value);
      if (!hasLetter || !hasDigit) {
        event.preventDefault();
        if (message) { message.textContent = '密码需要包含字母与数字。'; message.hidden = false; }
        password.focus();
        return;
      }
      if (!confirm.checkValidity()) {
        event.preventDefault();
        confirm.reportValidity();
        return;
      }
    }
    if (submit && !event.defaultPrevented) {
      submit.disabled = true;
      submit.classList.add('is-submitting');
      const label = submit.querySelector('.submit-label');
      if (label) label.textContent = mode === 'login' ? '正在验证账户…' : '正在创建账户…';
    }
  });
  // Restore when back-forward cache reopens an already submitted form.
  window.addEventListener('pageshow', () => {
    if (submit) { submit.disabled = false; submit.classList.remove('is-submitting'); }
    const label = submit?.querySelector('.submit-label');
    if (label) label.textContent = mode === 'login' ? '进入工作空间' : '创建账户';
  });
  passwordFeedback();
})();
