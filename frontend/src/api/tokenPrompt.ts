// Minimal access-token handling for servers that set DEALSCOPE_API_TOKEN.
// The token lives in localStorage (per browser) and is sent as X-DealScope-Token on every API call.

const KEY = "dealscope.apiToken";

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null; // storage blocked: the prompt will simply reappear
  }
}

export function storeToken(token: string): void {
  try {
    window.localStorage.setItem(KEY, token);
  } catch {
    /* storage blocked: token only lasts for this page load */
  }
  memoryToken = token;
}

let memoryToken: string | null = null;

export function currentToken(): string | null {
  return memoryToken ?? getStoredToken();
}

export function clearToken(): void {
  memoryToken = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

let pending: Promise<string | null> | null = null;

/** Ask the person for the access token in a native, focus-trapping <dialog>. Resolves null when dismissed. */
export function promptForToken(message: string): Promise<string | null> {
  if (pending) return pending;
  pending = new Promise<string | null>((resolve) => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-labelledby", "ds-token-title");
    dialog.style.cssText =
      "max-width:26rem;width:calc(100% - 32px);padding:20px;border:1px solid var(--ink);border-radius:6px;" +
      "background:var(--surface);color:var(--ink);";
    const form = document.createElement("form");
    form.method = "dialog";
    const title = document.createElement("h2");
    title.id = "ds-token-title";
    title.textContent = "Access token needed";
    title.style.cssText = "margin:0 0 8px;font-size:1.1rem;";
    const text = document.createElement("p");
    text.textContent = message;
    text.style.cssText = "margin:0 0 12px;";
    const label = document.createElement("label");
    label.textContent = "Access token";
    label.htmlFor = "ds-token-input";
    label.style.cssText = "display:block;margin-bottom:4px;";
    const input = document.createElement("input");
    input.id = "ds-token-input";
    input.type = "password";
    input.autocomplete = "off";
    input.required = true;
    input.style.cssText = "width:100%;box-sizing:border-box;padding:8px;margin-bottom:12px;background:var(--surface);color:var(--ink);border:1px solid var(--ink-2);";
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    const ok = document.createElement("button");
    ok.type = "submit";
    ok.textContent = "Save and retry";
    row.append(cancel, ok);
    form.append(title, text, label, input, row);
    dialog.append(form);
    document.body.append(dialog);

    let result: string | null = null;
    const finish = () => {
      dialog.close();
      dialog.remove();
      pending = null;
      if (previouslyFocused && previouslyFocused.isConnected) previouslyFocused.focus();
      resolve(result);
    };
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v) return;
      result = v;
      finish();
    });
    cancel.addEventListener("click", finish);
    dialog.addEventListener("cancel", (e) => {
      e.preventDefault();
      finish();
    });
    dialog.showModal();
    input.focus();
  });
  return pending;
}
