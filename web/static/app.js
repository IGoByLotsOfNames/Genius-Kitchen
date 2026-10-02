"use strict";

const paths = {
  pantry: '<path d="M4 8h16v13H4zM3 4h18v4H3zM9 12h6"/>',
  book: '<path d="M12 5c-3-2-7-2-10-1v15c4-1 7 0 10 2 3-2 6-3 10-2V4c-3-1-7-1-10 1zm0 0v16"/>',
  arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
  leaf: '<path d="M20 3C7 2 2 7 4 14c2 7 14 9 16-11zM3 21 15 9"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert: '<path d="m12 3 10 17H2zM12 9v4m0 3v.1"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  edit: '<path d="m14 5 5 5M4 20l5-1L20 8a3.5 3.5 0 0 0-5-5L4 14z"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  refresh: '<path d="M20 7a9 9 0 1 0 1 8M20 2v6h-6"/>',
  backup: '<path d="M4 5h16v4H4zM6 9v12h12V9m-9 4h6M6 2h12"/>',
  power: '<path d="M12 2v10M6 5a9 9 0 1 0 12 0"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  upload: '<path d="M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  spark: '<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3z"/>',
  bowl: '<path d="M3 11h18c0 6-4 9-9 9s-9-3-9-9zM9 21h6M8 7c-3-3 2-3 0-6m8 6c-3-3 2-3 0-6"/>',
  egg: '<path d="M19 14c0 5-3 8-7 8s-7-3-7-8S8 2 12 2s7 7 7 12zM8 15c0 2 1 3 2 3"/>',
  carrot: '<path d="M5 19 3 22l3-1L18 9c2-3-2-7-5-5zm7-11 3 3M9 11l2 2M17 5l2-4m-1 5 5-2"/>',
  milk: '<path d="M8 2h8v4l3 4v12H5V10l3-4zm0 4h8M5 10h14M9 14h6v4H9z"/>',
  fruit: '<path d="M12 7C3 1 0 13 7 21c2 2 3-1 5-1s3 3 5 1c7-8 4-20-5-14zm0 0c-1-4 2-5 5-5"/>',
  plate: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M10 10h4m-4 4h4"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.leaf}</svg>`;
document.querySelectorAll("[data-icon]").forEach(el => { el.innerHTML = icon(el.dataset.icon); });
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[ch]));
const dateLabel = value => new Intl.DateTimeFormat(undefined, {day:"numeric",month:"short"}).format(new Date(`${value}T12:00:00`));
let state = null;
let filter = "all";
let recipeFilter = "all";
let page = "pantry";
let editing = null;
let editRevision = null;
let busy = false;
let stopped = false;
let syncVersion = 0;
let loadNumber = 0;
let formGeneration = 0;
let toastTimer;
let pendingConfirmation;

function toast(message, bad = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").classList.toggle("bad", bad);
  $("toast").hidden = false;
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, bad ? 6500 : 3400);
}

async function request(path, options = {}) {
  const response = await fetch(path, {cache:"no-store", ...options});
  let result;
  try { result = await response.json(); } catch { throw new Error("The pantry could not read the response. Please try again."); }
  if (!response.ok) {
    const error = new Error(result.error || "Something went wrong. Please try again.");
    error.status = response.status;
    throw error;
  }
  return result;
}

async function load(silent = false) {
  if (stopped || busy) return;
  const version = syncVersion;
  const number = ++loadNumber;
  const isCurrent = () => version === syncVersion && number === loadNumber && !busy && !stopped;
  try {
    const next = await request("/api/state");
    if (!isCurrent()) return;
    state = next;
    $("connection-error").hidden = true;
    $("connection-label").textContent = "Saved on this computer";
    render();
  } catch (error) {
    if (!isCurrent()) return;
    $("connection-error").textContent = `${error.message} If the app was closed, reopen GeniusKitchen-Web to reconnect.`;
    $("connection-error").hidden = false;
    $("connection-label").textContent = "Pantry unavailable";
    if (!silent) toast("Could not open your pantry.", true);
  }
}

async function mutate(path, method, body, revision = state?.revision) {
  if (!state || stopped) throw new Error("Open the app again to reconnect to your pantry.");
  if (busy) throw new Error("Please wait for the current change to finish.");
  busy = true;
  syncVersion++;
  try {
    const next = await request(path, {method, headers:{"Content-Type":"application/json", "X-CSRF-Token":state.csrf_token, "If-Match":revision}, body:JSON.stringify(body ?? {})});
    if (next.items) { state = next; render(); }
    return next;
  } catch (error) {
    if (error.status === 409) {
      try {
        state = await request("/api/state");
        render();
        error.message = "The pantry changed. Review the latest ingredients and reopen this action before saving.";
      } catch {
        error.message = "The pantry changed, but could not be refreshed. Refresh your pantry and reopen this action before saving.";
      }
    }
    throw error;
  } finally { busy = false; }
}

function foodStyle(item) {
  const category = item.category.toLowerCase();
  if (category.includes("dairy")) return {icon: item.name.toLowerCase().includes("egg") ? "egg" : "milk", tone:"apricot"};
  if (category.includes("fruit")) return {icon:"fruit",tone:"rose"};
  if (category.includes("veget")) return {icon:"carrot",tone:"mint"};
  return {icon:"pantry",tone:"mint"};
}

function expiryText(item) {
  const days = item.days_until_expiry;
  if (days < 0) return `Expired ${-days === 1 ? "yesterday" : `${-days} days ago`}`;
  if (days === 0) return "Use today";
  if (days === 1) return "Use tomorrow";
  return `${days} days left`;
}

function renderPantry() {
  if (!state) return;
  const query = $("search").value.trim().toLocaleLowerCase();
  const visible = state.items.filter(item => (filter === "all" || item.status === filter) && `${item.name} ${item.category}`.toLocaleLowerCase().includes(query));
  $("ingredient-count").textContent = state.items.length;
  $("pantry-empty").hidden = state.items.length !== 0;
  $("search-empty").hidden = state.items.length === 0 || visible.length > 0;
  $("inventory-body").innerHTML = visible.map(item => {
    const art = foodStyle(item);
    return `<tr><td><div class="ingredient-cell"><span class="food-icon ${art.tone}">${icon(art.icon)}</span><span><span class="ingredient-name">${escapeHTML(item.name)}</span><span class="ingredient-category">${escapeHTML(item.category || "Other")}</span></span></div></td><td class="quantity-cell">${escapeHTML(Number(item.quantity).toLocaleString(undefined,{maximumSignificantDigits:8}))} ${escapeHTML(item.unit)}</td><td><span class="expiry-date">${escapeHTML(dateLabel(item.expires_on))}</span><span class="expiry-pill ${escapeHTML(item.status)}">${escapeHTML(expiryText(item))}</span></td><td><div class="row-actions"><button class="icon-button" data-edit="${escapeHTML(item.id)}" aria-label="Edit ${escapeHTML(item.name)}" title="Edit ${escapeHTML(item.name)}">${icon("edit")}</button><button class="icon-button" data-delete="${escapeHTML(item.id)}" aria-label="Remove ${escapeHTML(item.name)}" title="Remove ${escapeHTML(item.name)}">${icon("trash")}</button></div></td></tr>`;
  }).join("");
  $("visible-count").textContent = `${visible.length} of ${state.items.length} ingredients · ordered by expiry`;
  document.querySelectorAll("[data-filter]").forEach(button => {
    const active = button.dataset.filter === filter;
    button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
  });
}

const recipeArt = recipe => recipe.name.includes("Pancake") || recipe.name.includes("Omelette") ? "egg" : recipe.name.includes("Soup") ? "bowl" : recipe.name.includes("Rice") ? "carrot" : "plate";

function renderRecipes() {
  if (!state) return;
  const ready = state.recipes.filter(recipe => recipe.missing.length === 0);
  const visible = recipeFilter === "ready" ? ready : state.recipes;
  $("ready-description").textContent = ready.length ? `${ready.length} recipe${ready.length === 1 ? " has" : "s have"} every ingredient name in your pantry. Let's make something good.` : "A little inspiration for the ingredients you already have.";
  $("aside-count").textContent = `${state.recipes.length} RECIPES`;
  $("recipe-teasers").innerHTML = state.recipes.slice(0,3).map(recipe => `<button class="recipe-teaser" data-recipe="${escapeHTML(recipe.id)}"><span class="teaser-art">${icon(recipeArt(recipe))}</span><span><span class="teaser-name">${escapeHTML(recipe.name)}</span><span class="teaser-coverage">${Math.round(recipe.coverage*100)}% ingredients available</span></span>${icon("arrow")}</button>`).join("");
  $("recipe-count").textContent = visible.length;
  $("recipes-empty").hidden = visible.length !== 0;
  $("recipe-grid").innerHTML = visible.map((recipe, index) => `<article class="recipe-card"><div class="recipe-art art-${index%6}" aria-hidden="true">${icon(recipeArt(recipe))}</div><div class="recipe-card-content"><h3>${escapeHTML(recipe.name)}</h3><div class="coverage-line"><span>Ingredients available</span><strong>${Math.round(recipe.coverage*100)}%</strong></div><progress max="1" value="${recipe.coverage}" aria-label="${escapeHTML(recipe.name)} ingredient coverage"></progress><p class="missing-line">${recipe.missing.length ? `Missing: ${escapeHTML(recipe.missing.join(", "))}` : "Every ingredient name is in your pantry."}</p><button class="secondary-button" data-recipe="${escapeHTML(recipe.id)}">See recipe${icon("arrow")}</button></div></article>`).join("");
  document.querySelectorAll("[data-recipe-filter]").forEach(button => {
    const active = button.dataset.recipeFilter === recipeFilter;
    button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
  });
}

function render() {
  if (!state) return;
  $("nav-count").textContent = state.items.length;
  $("stat-total").textContent = state.items.length;
  $("stat-soon").textContent = state.items.filter(item => item.status === "soon").length;
  $("stat-expired").textContent = state.items.filter(item => item.status === "expired").length;
  $("sample-label").hidden = !state.demo_mode;
  $("today-label").textContent = new Intl.DateTimeFormat(undefined,{day:"numeric",month:"long",year:"numeric"}).format(new Date(`${state.today}T12:00:00`));
  renderPantry(); renderRecipes();
  if ($("recipe-dialog").open && $("recipe-detail").dataset.id) renderRecipeDetail($("recipe-detail").dataset.id);
}

function changePage(next) {
  page = next;
  $("pantry-page").hidden = page !== "pantry";
  $("recipes-page").hidden = page !== "recipes";
  $("breadcrumb").textContent = page === "pantry" ? "MY PANTRY / OVERVIEW" : "RECIPE BOOK / IDEAS";
  document.title = `Genius Kitchen · ${page === "pantry" ? "Your pantry" : "Recipe ideas"}`;
  document.querySelectorAll(".nav-item").forEach(button => {
    const active = button.dataset.page === page;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current","page"); else button.removeAttribute("aria-current");
  });
  window.scrollTo({top:0,behavior:"instant"});
}

function openIngredient(item = null) {
  if (!state) return toast("Your pantry is still connecting.", true);
  if (stopped) return toast("Reopen the app to edit your pantry.", true);
  formGeneration++;
  editing = item;
  editRevision = state.revision;
  $("ingredient-form").reset();
  $("ingredient-dialog-title").textContent = item ? "Edit ingredient" : "Add an ingredient";
  $("ingredient-name").value = item?.name || "";
  $("ingredient-quantity").value = item?.quantity ?? 1;
  $("ingredient-unit").value = item?.unit || "item";
  const category = item?.category || "Other";
  if (![...$("ingredient-category").options].some(option => option.value === category)) {
    const option = new Option(category, category); $("ingredient-category").add(option);
  }
  $("ingredient-category").value = category;
  $("ingredient-expiry").value = item?.expires_on || state.today;
  $("form-error").hidden = true;
  $("save-ingredient").disabled = false;
  $("ingredient-dialog").showModal();
  $("ingredient-name").focus();
}

function renderRecipeDetail(id) {
  const recipe = state?.recipes.find(item => String(item.id) === String(id));
  if (!recipe) return;
  $("recipe-detail").dataset.id = String(id);
  $("recipe-detail").innerHTML = `<h2 id="recipe-dialog-title">${escapeHTML(recipe.name)}</h2><div class="coverage-line"><span>Ingredients available</span><strong>${Math.round(recipe.coverage*100)}%</strong></div><progress max="1" value="${recipe.coverage}" aria-label="Ingredient coverage"></progress><h3>What you'll need</h3><ul class="ingredient-checklist">${recipe.ingredients.map(name => `<li class="${recipe.missing.includes(name) ? "missing" : ""}">${icon(recipe.missing.includes(name) ? "plus" : "check")}<span>${escapeHTML(name)}${recipe.missing.includes(name) ? " · missing" : ""}</span></li>`).join("")}</ul><h3>Let's make it</h3><ol class="instructions">${recipe.instructions.map(step => `<li>${escapeHTML(step)}</li>`).join("")}</ol><p class="small-note">This illustrative recipe does not specify quantities or food-safety requirements. Check what you need before cooking.</p>`;
}

function confirmAction(title, message, label) {
  if (pendingConfirmation) pendingConfirmation(false);
  $("confirm-title").textContent = title; $("confirm-message").textContent = message; $("confirm-ok").textContent = label;
  $("confirm-dialog").showModal();
  $("confirm-cancel").focus();
  return new Promise(resolve => { pendingConfirmation = resolve; });
}
function endConfirmation(answer) {
  const resolve = pendingConfirmation; pendingConfirmation = null;
  $("confirm-dialog").close(); if (resolve) resolve(answer);
}
$("confirm-ok").addEventListener("click", () => endConfirmation(true));
$("confirm-cancel").addEventListener("click", () => endConfirmation(false));
$("confirm-dialog").addEventListener("cancel", () => endConfirmation(false));

document.addEventListener("click", async event => {
  const button = event.target.closest("button"); if (!button) return;
  if (button.dataset.page) changePage(button.dataset.page);
  if (button.hasAttribute("data-add")) openIngredient();
  if (button.dataset.close) {
    if (button.dataset.close === "confirm-dialog") endConfirmation(false); else $(button.dataset.close).close();
  }
  if (button.dataset.filter || button.dataset.statFilter) {
    filter = button.dataset.filter || button.dataset.statFilter; renderPantry();
  }
  if (button.dataset.recipeFilter) { recipeFilter = button.dataset.recipeFilter; renderRecipes(); }
  if (button.dataset.recipe && state) { renderRecipeDetail(button.dataset.recipe); $("recipe-dialog").showModal(); }
  if (button.dataset.edit) openIngredient(state?.items.find(item => String(item.id) === button.dataset.edit));
  if (button.dataset.delete && state) {
    const item = state.items.find(entry => String(entry.id) === button.dataset.delete); if (!item) return;
    const revision = state.revision;
    if (await confirmAction(`Remove ${item.name}?`, "This ingredient will be removed from your pantry and your recipe matches will update.", "Remove ingredient")) {
      try { await mutate(`/api/items/${encodeURIComponent(item.id)}`, "DELETE", {}, revision); toast(`${item.name} removed from your pantry.`); }
      catch (error) { toast(error.message, true); }
    }
  }
});

$("ingredient-form").addEventListener("submit", async event => {
  event.preventDefault();
  const generation = formGeneration;
  const editingItem = editing;
  const revision = editRevision;
  const quantity = Number($("ingredient-quantity").value);
  if (!Number.isFinite(quantity) || quantity <= 0) {
    $("form-error").textContent = "Enter a quantity greater than zero."; $("form-error").hidden = false; return;
  }
  const item = {name:$("ingredient-name").value.trim(),quantity,unit:$("ingredient-unit").value.trim(),category:$("ingredient-category").value,expires_on:$("ingredient-expiry").value};
  $("save-ingredient").disabled = true;
  try {
    await mutate(editingItem ? `/api/items/${encodeURIComponent(editingItem.id)}` : "/api/items", editingItem ? "PATCH" : "POST", item, revision);
    if (generation === formGeneration) $("ingredient-dialog").close();
    toast(editingItem ? `${item.name} updated.` : `${item.name} added to your pantry.`);
  } catch (error) {
    if (generation === formGeneration) { $("form-error").textContent = error.message; $("form-error").hidden = false; }
    else toast(error.message, true);
  }
  finally { if (generation === formGeneration) $("save-ingredient").disabled = false; }
});

$("search").addEventListener("input", renderPantry);
$("clear-search").addEventListener("click", () => { $("search").value = ""; filter = "all"; renderPantry(); });
$("show-all-recipes").addEventListener("click", () => { recipeFilter = "all"; renderRecipes(); });
$("refresh-button").addEventListener("click", () => load());
$("backup-button").addEventListener("click", () => $("backup-dialog").showModal());
$("load-sample").addEventListener("click", async () => {
  try { await mutate("/api/demo", "POST", {}); toast("A sample pantry is ready to explore."); }
  catch (error) { toast(error.message, true); }
});
$("export-button").addEventListener("click", async () => {
  if (!state || stopped) return toast("Open the app to export your pantry.", true);
  try {
    const response = await fetch("/api/export", {cache:"no-store"});
    if (!response.ok) throw new Error("Could not export the pantry. Please try again.");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = `genius-kitchen-inventory-${state.today}.json`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Your pantry backup is ready.");
  } catch (error) { toast(error.message, true); }
});
$("import-button").addEventListener("click", () => $("import-file").click());
$("import-file").addEventListener("change", async event => {
  const file = event.target.files[0]; event.target.value = ""; if (!file) return;
  if (!state || stopped) return toast("Open the app to import a pantry.", true);
  try {
    if (file.size > 1000000) throw new Error("Choose an inventory file smaller than 1 MB.");
    let items; try { items = JSON.parse(await file.text()); } catch { throw new Error("This file isn't valid JSON. Choose an exported pantry file."); }
    if (!Array.isArray(items)) throw new Error("The inventory file must contain a list of ingredients.");
    const revision = state.revision;
    $("backup-dialog").close();
    if (await confirmAction("Replace this pantry?", `Import ${items.length} ingredient${items.length === 1 ? "" : "s"} from ${file.name}? This replaces all ${state.items.length} ingredients currently in the browser pantry.`, "Import pantry")) {
      await mutate("/api/import", "POST", {items}, revision); toast("Your pantry has been imported.");
    }
  } catch (error) { toast(error.message, true); }
});
$("stop-button").addEventListener("click", async () => {
  if (stopped) return;
  if (await confirmAction("Close Genius Kitchen?", "Your saved pantry will be here when you return. Reopen GeniusKitchen-Web to use the app again.", "Close app")) {
    try {
      await mutate("/api/shutdown", "POST", {}); stopped = true;
      $("connection-label").textContent = "App closed · pantry saved";
      $("connection-error").textContent = "Your pantry is saved. You can close this tab and reopen GeniusKitchen-Web whenever you need it.";
      $("connection-error").classList.remove("error"); $("connection-error").hidden = false;
      toast("Your pantry is saved. See you next time.");
    } catch (error) { toast(error.message, true); }
  }
});

window.addEventListener("focus", () => load(true));
setInterval(() => { if (!document.hidden) load(true); }, 30000);
load();
