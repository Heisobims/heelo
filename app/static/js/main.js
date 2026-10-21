/* Heelo - main.js
   Alpine.js components defined as plain global functions.
   main.js loads BEFORE Alpine (see base.html script order), so these are
   available when Alpine evaluates x-data="componentName()" expressions.
   ------------------------------------------------------------------ */

// ── CSRF ──────────────────────────────────────────────────────────────────────
// Double-submit token (app/middleware/csrf.py): the server sets a readable
// csrf_token cookie; every non-GET fetch()/HTMX call must echo it back as
// X-CSRF-Token. Wrapping fetch once here covers every Alpine component's
// fetch() call without touching each template individually.
;(() => {
  const originalFetch = window.fetch.bind(window)
  window.fetch = (input, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    if (method !== 'GET' && method !== 'HEAD') {
      const token = getCookie('csrf_token') || document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
      if (token) {
        const headers = new Headers(init.headers || {})
        headers.set('X-CSRF-Token', token)
        init = { ...init, headers }
      }
    }
    return originalFetch(input, init)
  }
})()

// ── HTMX global config ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.addEventListener('htmx:configRequest', (evt) => {
    const token = getCookie('heelo_access')
    if (token) evt.detail.headers['Authorization'] = `Bearer ${token}`

    const csrfToken = getCookie('csrf_token')
    if (csrfToken && evt.detail.verb !== 'get') {
      evt.detail.headers['X-CSRF-Token'] = csrfToken
    }
  })

  document.addEventListener('htmx:responseError', (evt) => {
    const target = evt.detail.target
    let msg = 'Something went wrong. Please try again.'
    try {
      const body = JSON.parse(evt.detail.xhr.responseText)
      msg = body?.error?.message || msg
    } catch (_) {}
    showInlineError(target, msg)
  })

  initSiteNav()
  initScrollReveal()
})

// ── Shared site nav (scroll shadow + mobile hamburger) ─────────────────────────
// Powers `partials/site_nav.html`, included on every public, non-dashboard page.
function initSiteNav() {
  const nav = document.getElementById('site-nav')
  if (!nav) return

  window.addEventListener('scroll', () => {
    nav.classList.toggle('sld', window.scrollY > 24)
  }, { passive: true })

  const btn = document.getElementById('site-nav-hamburger')
  const menu = document.getElementById('site-nav-mobile-menu')
  if (btn && menu) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation()
      btn.classList.toggle('open')
      menu.classList.toggle('open')
    })
    menu.querySelectorAll('a').forEach((a) => {
      a.addEventListener('click', () => {
        btn.classList.remove('open')
        menu.classList.remove('open')
      })
    })
    document.addEventListener('click', (e) => {
      if (menu.classList.contains('open') && !menu.contains(e.target) && !btn.contains(e.target)) {
        btn.classList.remove('open')
        menu.classList.remove('open')
      }
    })
  }
}

// ── Lively scroll reveal animations ───────────────────────────────────────────
function initScrollReveal() {
  if (!('IntersectionObserver' in window)) {
    document.querySelectorAll('.mpl-reveal').forEach(el => el.classList.add('revealed'))
    return
  }

  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed')
        obs.unobserve(entry.target)
      }
    })
  }, {
    threshold: 0.08,
    rootMargin: '0px 0px -30px 0px'
  })

  document.querySelectorAll('.mpl-reveal').forEach(el => observer.observe(el))
}

function getCookie(name) {
  return document.cookie
    .split('; ')
    .find(r => r.startsWith(name + '='))
    ?.split('=')[1] || null
}

function showInlineError(container, message) {
  let el = container?.querySelector?.('.inline-error')
  if (!el) {
    el = document.createElement('p')
    el.className = 'inline-error'
    container?.appendChild(el)
  }
  el.textContent = message
  el.style.display = 'block'
}

// ── Alpine.js components (global functions) ───────────────────────────────────
// Alpine evaluates x-data="loginForm()" by calling window.loginForm(),
// which works as long as these are defined before Alpine.start() runs.
//
// Note: there is no global `registerForm()` here on purpose: the event
// ticket-purchase page (events/register.html) defines its own page-local
// `registerForm()` for x-data="registerForm()". A same-named stub here
// used to silently clobber it (main.js loads after that inline script but
// before Alpine starts), breaking ticket checkout on every event page.
// auth/register.html itself doesn't use Alpine at all, so nothing needs it.

function loginForm() {
  return {
    email: '',
    password: '',
    rememberMe: false,
    showPassword: false,
    loading: false,
    errors: {},

    async submit() {
      this.errors = {}
      this.loading = true
      try {
        const res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: this.email,
            password: this.password,
            remember_me: this.rememberMe,
          }),
        })
        const data = await res.json()
        if (!res.ok) {
          this.errors._global = data?.error?.message || 'Login failed.'
          return
        }
        const next = new URLSearchParams(window.location.search).get('next')
        window.location.href = next || '/dashboard'
      } catch (_) {
        this.errors._global = 'Network error. Please try again.'
      } finally {
        this.loading = false
      }
    },
  }
}

function otpInput(submitUrl, email) {
  return {
    digits: ['', '', '', '', '', ''],
    error: '',
    loading: false,
    resendCountdown: 30,
    canResend: false,

    init() {
      this.startResendTimer()
      this.$nextTick(() => this.$refs.d0?.focus())
    },

    startResendTimer() {
      this.canResend = false
      this.resendCountdown = 30
      const t = setInterval(() => {
        this.resendCountdown--
        if (this.resendCountdown <= 0) {
          this.canResend = true
          clearInterval(t)
        }
      }, 1000)
    },

    get code() { return this.digits.join('') },
    get filled() { return this.digits.every(d => d.length === 1) },

    onInput(idx, evt) {
      const val = evt.target.value.replace(/\D/g, '')
      this.digits[idx] = val.slice(-1)
      evt.target.value = this.digits[idx]
      if (this.digits[idx] && idx < 5) {
        this.$refs[`d${idx + 1}`]?.focus()
      }
      if (this.filled) this.submit()
    },

    onKeydown(idx, evt) {
      if (evt.key === 'Backspace') {
        if (!this.digits[idx] && idx > 0) {
          this.digits[idx - 1] = ''
          this.$refs[`d${idx - 1}`].value = ''
          this.$refs[`d${idx - 1}`]?.focus()
        }
      } else if (evt.key === 'ArrowLeft' && idx > 0) {
        this.$refs[`d${idx - 1}`]?.focus()
      } else if (evt.key === 'ArrowRight' && idx < 5) {
        this.$refs[`d${idx + 1}`]?.focus()
      }
    },

    onPaste(evt) {
      evt.preventDefault()
      const pasted = evt.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
      pasted.split('').forEach((ch, i) => {
        if (i < 6) {
          this.digits[i] = ch
          if (this.$refs[`d${i}`]) this.$refs[`d${i}`].value = ch
        }
      })
      this.$refs[`d${Math.min(pasted.length, 5)}`]?.focus()
      if (pasted.length === 6) this.submit()
    },

    async submit() {
      if (!this.filled || this.loading) return
      this.loading = true
      this.error = ''
      try {
        const res = await fetch(submitUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, otp: this.code }),
        })
        const data = await res.json()
        if (!res.ok) {
          this.error = data?.error?.message || 'Incorrect code.'
          this.digits = ['', '', '', '', '', '']
          this.$nextTick(() => this.$refs.d0?.focus())
          return
        }
        window.location.href = '/onboarding/role'
      } catch (_) {
        this.error = 'Network error. Please try again.'
      } finally {
        this.loading = false
      }
    },

    async resend() {
      if (!this.canResend) return
      await fetch('/api/v1/auth/resend-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      this.digits = ['', '', '', '', '', '']
      this.$nextTick(() => this.$refs.d0?.focus())
      this.startResendTimer()
    },
  }
}

function roleSelect() {
  return {
    selected: '',
    loading: false,

    async pick(role) {
      this.selected = role
      this.loading = true
      try {
        const res = await fetch('/api/v1/auth/select-role', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role }),
        })
        if (res.ok) {
          window.location.href = role === 'attendee' ? '/home' : '/dashboard'
        } else {
          this.loading = false
          this.selected = ''
        }
      } catch (_) {
        this.loading = false
        this.selected = ''
      }
    },
  }
}

function forgotPasswordForm() {
  return {
    email: '',
    loading: false,
    sent: false,
    error: '',

    async submit() {
      this.error = ''
      this.loading = true
      try {
        await fetch('/api/v1/auth/forgot-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: this.email }),
        })
        this.sent = true
      } catch (_) {
        this.error = 'Network error. Please try again.'
      } finally {
        this.loading = false
      }
    },
  }
}

function resetPasswordForm(token) {
  return {
    password: '',
    showPassword: false,
    loading: false,
    done: false,
    error: '',

    async submit() {
      this.error = ''
      this.loading = true
      try {
        const res = await fetch('/api/v1/auth/reset-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token, new_password: this.password }),
        })
        if (!res.ok) {
          const data = await res.json()
          this.error = data?.error?.message || 'Reset failed.'
          return
        }
        this.done = true
        setTimeout(() => { window.location.href = '/login' }, 2000)
      } catch (_) {
        this.error = 'Network error. Please try again.'
      } finally {
        this.loading = false
      }
    },
  }
}

function loadingBtn() {
  return {
    loading: false,
    trigger() { this.loading = true },
  }
}

// ── AI streaming helper ───────────────────────────────────────────────────────
async function streamAIResponse(url, body, targetEl, onDone) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    targetEl.textContent = 'Could not generate a response. Please try again.'
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  targetEl.textContent = ''

  const cursor = document.createElement('span')
  cursor.className = 'ai-cursor'
  targetEl.appendChild(cursor)

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const chunk = line.slice(6)
        if (chunk === '[DONE]') break
        targetEl.insertBefore(document.createTextNode(chunk), cursor)
      }
    }
  }
  cursor.remove()
  if (onDone) onDone(targetEl.textContent)
}

window.Heelo = { streamAIResponse }
