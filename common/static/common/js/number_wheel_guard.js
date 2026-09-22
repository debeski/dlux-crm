(function () {
    // A wheel over a focused number input spins its value by one step. Blur the
    // input instead, so the wheel scrolls the page and the value stays put.
    document.addEventListener("wheel", function (event) {
        var input = event.target;
        if (input instanceof HTMLInputElement && input.type === "number" && input === document.activeElement) {
            input.blur();
        }
    }, { passive: true });
})();
