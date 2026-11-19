// Halaman Detail: daftar "Pilih pos" ikut menggulir ke pos terpilih (mis. dipilih lewat peta), supaya yang
// disorot selalu kelihatan. Hanya menggulir daftarnya sendiri, bukan halaman.
(function () {
  function reveal() {
    var sel = document.querySelector(".pl-items .pl-item.sel");
    if (!sel) return;
    var box = sel.closest(".pl-items");
    if (!box || box.scrollHeight <= box.clientHeight) return;
    var top = sel.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop,
        bottom = top + sel.offsetHeight;
    if (top < box.scrollTop || bottom > box.scrollTop + box.clientHeight) {
      box.scrollTo({ top: top - (box.clientHeight - sel.offsetHeight) / 2, behavior: "smooth" });
    }
  }
  var pending = null;
  new MutationObserver(function () {
    if (pending) cancelAnimationFrame(pending);
    pending = requestAnimationFrame(reveal);
  }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
})();
