import {
  createMemoryHistory,
  createRouter,
  createWebHistory,
  type Router
} from "vue-router";

import AiopsWorkspaceLayout from "../layouts/AiopsWorkspaceLayout.vue";
import WorkspaceLayout from "../layouts/WorkspaceLayout.vue";
import DemoView from "../views/DemoView.vue";
import AuthView from "../views/AuthView.vue";
import AiopsAlertsView from "../views/AiopsAlertsView.vue";
import AiopsCasesView from "../views/AiopsCasesView.vue";
import AiopsHistoryView from "../views/AiopsHistoryView.vue";
import AiopsOverviewView from "../views/AiopsOverviewView.vue";
import AiopsView from "../views/AiopsView.vue";
import ChatView from "../views/ChatView.vue";
import KnowledgeView from "../views/KnowledgeView.vue";
import McpView from "../views/McpView.vue";
import MetricsExplorerView from "../views/MetricsExplorerView.vue";
import ModelConfigView from "../views/ModelConfigView.vue";
import PersonalInfoView from "../views/PersonalInfoView.vue";
import ProfileAboutView from "../views/ProfileAboutView.vue";
import ProfileView from "../views/ProfileView.vue";
import PrometheusSourcesView from "../views/PrometheusSourcesView.vue";
import WorkspacePlaceholderView from "../views/WorkspacePlaceholderView.vue";

export interface AuthRouteAccess {
  initialize(): Promise<void>;
  isAuthenticated(): boolean;
}

export function createAppRouter(auth: AuthRouteAccess): Router {
  const router = createRouter({
    history: typeof window === "undefined" ? createMemoryHistory() : createWebHistory(),
    routes: [
      { path: "/demo", name: "demo", component: DemoView, meta: { offlineDemo: true } },
      { path: "/", redirect: "/aiops" },
      {
        path: "/login",
        name: "login",
        component: AuthView,
        props: { mode: "login" },
        meta: { publicOnly: true }
      },
      {
        path: "/register",
        name: "register",
        component: AuthView,
        props: { mode: "register" },
        meta: { publicOnly: true }
      },
      {
        path: "/",
        component: WorkspaceLayout,
        meta: { requiresAuth: true },
        children: [
          {
            path: "chat",
            name: "chat",
            component: ChatView,
            meta: { title: "对话" }
          },
          {
            path: "knowledge",
            name: "knowledge",
            component: KnowledgeView,
            meta: { title: "知识库" }
          },
          {
            path: "aiops",
            component: AiopsWorkspaceLayout,
            meta: { title: "AI 运维中心" },
            children: [
              {
                path: "",
                name: "aiops",
                component: AiopsView,
                meta: { title: "诊断台" }
              },
              {
                path: "overview",
                name: "aiops-overview",
                component: AiopsOverviewView,
                meta: { title: "总览" }
              },
              {
                path: "alerts",
                name: "aiops-alerts",
                component: AiopsAlertsView,
                meta: { title: "告警中心" }
              },
              {
                path: "cases",
                name: "aiops-cases",
                component: AiopsCasesView,
                meta: { title: "案例库" }
              },
              {
                path: "history",
                name: "aiops-history",
                component: AiopsHistoryView,
                meta: { title: "历史记录" }
              }
            ]
          },
          {
            path: "monitor/metrics",
            name: "monitor-metrics",
            component: MetricsExplorerView,
            meta: { title: "Prometheus 指标监控" }
          },
          {
            path: "monitor/sources",
            name: "monitor-sources",
            component: PrometheusSourcesView,
            meta: { title: "数据源管理" }
          },
          {
            path: "mcp",
            name: "mcp",
            component: McpView,
            meta: { title: "工具连接（MCP）" }
          },
          {
            path: "profile",
            component: ProfileView,
            redirect: "/profile/model",
            children: [
              {
                path: "model",
                name: "profile-model",
                component: ModelConfigView,
                meta: { title: "模型配置" }
              },
              {
                path: "info",
                name: "profile-info",
                component: PersonalInfoView,
                meta: { title: "个人信息" }
              },
              {
                path: "about",
                name: "profile-about",
                component: ProfileAboutView,
                meta: { title: "关于" }
              }
            ]
          }
        ]
      },
      { path: "/:pathMatch(.*)*", redirect: "/aiops" }
    ]
  });

  let initialization: Promise<void> | null = null;
  router.beforeEach(async (to) => {
    if (to.meta.offlineDemo === true) return true;
    initialization ??= auth.initialize();
    await initialization;
    const requiresAuth = to.matched.some((record) => record.meta.requiresAuth === true);
    const publicOnly = to.matched.some((record) => record.meta.publicOnly === true);
    if (requiresAuth && !auth.isAuthenticated()) {
      return { path: "/login", query: { redirect: to.fullPath } };
    }
    if (publicOnly && auth.isAuthenticated()) {
      return { path: "/aiops" };
    }
    return true;
  });

  return router;
}
