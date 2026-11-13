/**
 * NexHup Login Page Interactive Scripts
 */

// Toggle Password Visibility
function togglePassword(inputId, button) {
    const passwordInput = document.getElementById(inputId);
    const eyeSlash = button.querySelector(".eye-slash");

    if (passwordInput.type === "password") {
        passwordInput.type = "text";
        if (eyeSlash) eyeSlash.style.display = "none";
        button.setAttribute("aria-label", "Hide password");
    } else {
        passwordInput.type = "password";
        if (eyeSlash) eyeSlash.style.display = "block";
        button.setAttribute("aria-label", "Show password");
    }
}

// Client-side Form Validation
document.addEventListener("DOMContentLoaded", () => {
    const loginForm = document.getElementById("loginForm");

    if (loginForm) {
        loginForm.addEventListener("submit", (e) => {
            const emailInput = document.getElementById("email");
            const passwordInput = document.getElementById("password");

            if (!emailInput.value.trim() || !passwordInput.value.trim()) {
                e.preventDefault();
                alert("Please fill in both email and password.");
            }
        });
    }
});
