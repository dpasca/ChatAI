// Functions to manage the theme

function initializeTheme() {
  let isDarkTheme;
  // Check if the theme was previously saved in localStorage
  if (localStorage.getItem('theme')) {
    isDarkTheme = localStorage.getItem('theme') === 'dark';
  } else {
    // If not, use the system's theme
    isDarkTheme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  // Apply initial theme state without toggling
  applyTheme(isDarkTheme);
}

function toggleTheme() {
    const isDarkTheme = document.body.classList.contains('dark-theme');
    // Toggle theme to the opposite state
    applyTheme(!isDarkTheme);
}

function applyTheme(isDarkTheme) {
    const body = document.body;
    const themeToggleCheckbox = document.getElementById('theme-toggle');
    const navbar = document.getElementById('main-navbar');
    const moonIcon = document.querySelector('.bi-moon-stars-fill');
    const sunIcon = document.querySelector('.bi-sun-fill');

    // Apply theme class on body
    body.classList.toggle('dark-theme', isDarkTheme);

    // Update navbar classes for the theme
    if (isDarkTheme) {
        navbar.classList.remove('navbar-light', 'bg-light');
        navbar.classList.add('navbar-dark', 'bg-dark');
    } else {
        navbar.classList.remove('navbar-dark', 'bg-dark');
        navbar.classList.add('navbar-light', 'bg-light');
    }

    // Update checkbox based on current theme
    themeToggleCheckbox.checked = isDarkTheme;

    // Update icons visibility based on theme
    moonIcon.style.display = isDarkTheme ? 'none' : 'inline-block';
    sunIcon.style.display = isDarkTheme ? 'inline-block' : 'none';

    // Save theme preference
    localStorage.setItem('theme', isDarkTheme ? 'dark' : 'light');
}

window.addEventListener('load', function() {
  var navbarHeight = document.querySelector('.navbar').offsetHeight;
  navbarHeight += 8; // Add some padding
  document.body.style.paddingTop = navbarHeight + 'px';
});

