document.addEventListener("DOMContentLoaded", function () {
  // Apply saved preferences immediately
  var font = localStorage.getItem("pref-font") || "lexend";
  var size = localStorage.getItem("pref-size") || "medium";
  applyFont(font);
  applySize(size);

  // Build UI
  var btn = document.createElement("button");
  btn.id = "prefs-btn";
  btn.textContent = "⚙️ Reading";

  var panel = document.createElement("div");
  panel.id = "prefs-panel";
  panel.innerHTML =
    '<label for="font-select">Font</label>' +
    '<select id="font-select">' +
    '<option value="lexend">Lexend Deca</option>' +
    '<option value="opendyslexic">OpenDyslexic</option>' +
    '<option value="atkinson">Atkinson Hyperlegible</option>' +
    "</select>" +
    "<label>Size</label>" +
    '<div class="size-btns">' +
    '<button data-size="small">A-</button>' +
    '<button data-size="medium">A</button>' +
    '<button data-size="large">A+</button>' +
    "</div>" +
    '<button id="prefs-close">Close</button>';

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  // Set initial control states
  document.getElementById("font-select").value = font;
  updateSizeBtns(size);

  // Events
  btn.addEventListener("click", function () {
    panel.classList.toggle("open");
  });
  document.getElementById("prefs-close").addEventListener("click", function () {
    panel.classList.remove("open");
  });
  document.getElementById("font-select").addEventListener("change", function (e) {
    applyFont(e.target.value);
    localStorage.setItem("pref-font", e.target.value);
  });
  panel.querySelectorAll(".size-btns button").forEach(function (b) {
    b.addEventListener("click", function () {
      var s = this.getAttribute("data-size");
      applySize(s);
      localStorage.setItem("pref-size", s);
      updateSizeBtns(s);
    });
  });

  function applyFont(f) {
    document.body.classList.remove("font-lexend", "font-opendyslexic", "font-atkinson");
    document.body.classList.add("font-" + f);
  }

  function applySize(s) {
    document.body.classList.remove("font-small", "font-medium", "font-large");
    document.body.classList.add("font-" + s);
  }

  function updateSizeBtns(s) {
    var btns = panel.querySelectorAll(".size-btns button");
    btns.forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-size") === s);
    });
  }
});
