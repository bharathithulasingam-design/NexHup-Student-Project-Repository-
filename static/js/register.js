
function togglePassword(inputId, button) {
    const passwordInput = document.getElementById(inputId);

    if (!passwordInput) return;

    const eyeSlash = button.querySelector(".eye-slash");
    const isPassword = passwordInput.type === "password";

    passwordInput.type = isPassword ? "text" : "password";

    if (eyeSlash) {
        eyeSlash.style.display = isPassword ? "none" : "block";
    }

    button.setAttribute(
        "aria-label",
        isPassword ? "Hide password" : "Show password"
    );
}