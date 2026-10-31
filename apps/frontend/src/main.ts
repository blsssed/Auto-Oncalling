import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { createAppRouter } from "./router";
import { createAuthRouteAccess, useAuthStore } from "./stores/auth";
import { applyInitialTheme, useThemeStore } from "./stores/theme";
import "./styles.css";

applyInitialTheme();

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
useThemeStore(pinia).initialize();
app.use(createAppRouter(createAuthRouteAccess(useAuthStore(pinia))));
app.mount("#app");
