// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import AppEmptyState from "../src/components/AppEmptyState.vue";
import AppErrorState from "../src/components/AppErrorState.vue";
import AppFeedback from "../src/components/AppFeedback.vue";
import AppLoadingState from "../src/components/AppLoadingState.vue";
import WorkspaceNavigation from "../src/components/WorkspaceNavigation.vue";
import { useFeedbackStore } from "../src/stores/feedback";

afterEach(() => {
  vi.useRealTimers();
});

describe("application shell components", () => {
  it("renders accessible loading, empty, and error feedback", () => {
    expect(mount(AppLoadingState, { props: { label: "Loading workspace" } }).get("[role=status]").text()).toContain(
      "Loading workspace"
    );
    expect(mount(AppEmptyState, { props: { title: "No documents yet" } }).text()).toContain(
      "No documents yet"
    );
    expect(mount(AppErrorState, { props: { message: "Request failed" } }).get("[role=alert]").text()).toContain(
      "Request failed"
    );
  });

  it("uses Chinese labels for the active workspace route", () => {
    const wrapper = mount(WorkspaceNavigation, {
      props: { activePath: "/chat" },
      slots: { "chat-history": '<div data-testid="chat-history-slot">历史对话插槽</div>' },
      global: {
        stubs: {
          RouterLink: {
            props: ["to"],
            template: '<a :href="to"><slot /></a>'
          }
        }
      }
    });

    expect(wrapper.attributes("aria-label")).toBe("工作区导航");
    expect(wrapper.get('[aria-current="page"]').text()).toContain("对话");
    expect(wrapper.get('[data-testid="chat-history-slot"]').text()).toBe("历史对话插槽");
    expect(wrapper.text()).toContain("知识库");
    expect(wrapper.text()).toContain("AI 运维中心");
    expect(wrapper.text()).toContain("告警、诊断、案例、历史");
    const markup = wrapper.html();
    expect(markup.indexOf("历史对话插槽")).toBeGreaterThan(markup.indexOf('href="/chat"'));
    expect(markup.indexOf("历史对话插槽")).toBeLessThan(markup.indexOf('href="/knowledge"'));
  });

  it("keeps a single active aiops entry without nested sub links", () => {
    const wrapper = mount(WorkspaceNavigation, {
      props: { activePath: "/aiops/cases" },
      global: {
        stubs: {
          RouterLink: {
            props: ["to"],
            template: '<a :href="to"><slot /></a>'
          }
        }
      }
    });

    expect(wrapper.text()).toContain("AI 运维中心");
    expect(wrapper.findAll(".workspace-navigation__link--active")).toHaveLength(1);
    expect(wrapper.get(".workspace-navigation__link--active").text()).toContain("AI 运维中心");
    // AIOps 页签由工作区内部的页签栏承担，左栏不再重复渲染子链接。
    expect(wrapper.findAll(".workspace-navigation__sub-link--active")).toHaveLength(0);
    expect(wrapper.findAll(".workspace-navigation__link")).toHaveLength(5);
  });

  it("keeps the monitor center group highlighted across monitor routes", () => {
    const wrapper = mount(WorkspaceNavigation, {
      props: { activePath: "/monitor/sources" },
      global: {
        stubs: {
          RouterLink: {
            props: ["to"],
            template: '<a :href="to"><slot /></a>'
          }
        }
      }
    });

    expect(wrapper.text()).toContain("监控中心");
    expect(wrapper.text()).toContain("Prometheus 指标监控");
    expect(wrapper.text()).toContain("数据源管理");
    expect(wrapper.findAll(".workspace-navigation__link--active")).toHaveLength(1);
    expect(wrapper.get(".workspace-navigation__link--active").text()).toContain("监控中心");
    expect(wrapper.get(".workspace-navigation__sub-link--active").text()).toContain("数据源管理");
  });

  it("renders six flat compact entries for the mobile bottom bar", () => {
    const wrapper = mount(WorkspaceNavigation, {
      props: { activePath: "/monitor/metrics", compact: true },
      global: {
        stubs: {
          RouterLink: {
            props: ["to"],
            template: '<a :href="to"><slot /></a>'
          }
        }
      }
    });

    const links = wrapper.findAll(".workspace-navigation__link");
    expect(links.map((link) => link.text())).toEqual(["对话", "知识库", "监控", "运维", "工具", "我的"]);
    expect(wrapper.findAll(".workspace-navigation__sub")).toHaveLength(0);
    expect(wrapper.findAll(".workspace-navigation__link--active")).toHaveLength(1);
    expect(wrapper.get(".workspace-navigation__link--active").text()).toContain("监控");
  });

  it("keeps the profile center out of the desktop rail but active in the compact bar", () => {
    const desktop = mount(WorkspaceNavigation, {
      props: { activePath: "/profile/model" },
      global: {
        stubs: {
          RouterLink: {
            props: ["to"],
            template: '<a :href="to"><slot /></a>'
          }
        }
      }
    });
    expect(desktop.text()).not.toContain("个人中心");

    const compact = mount(WorkspaceNavigation, {
      props: { activePath: "/profile/model", compact: true },
      global: {
        stubs: {
          RouterLink: {
            props: ["to"],
            template: '<a :href="to"><slot /></a>'
          }
        }
      }
    });
    expect(compact.text()).toContain("我的");
    const activeLinks = compact.findAll(".workspace-navigation__link--active");
    expect(activeLinks).toHaveLength(1);
    expect(activeLinks[0]!.text()).toContain("我的");
  });

  it("automatically dismisses global feedback three seconds after the latest message", async () => {
    vi.useFakeTimers();
    const pinia = createPinia();
    setActivePinia(pinia);
    const wrapper = mount(AppFeedback, { global: { plugins: [pinia] } });
    const feedback = useFeedbackStore();

    feedback.show("success", "反馈已保存");
    await nextTick();
    expect(wrapper.get("[role=alert]").text()).toContain("反馈已保存");

    await vi.advanceTimersByTimeAsync(2_000);
    feedback.show("success", "MCP 连接已保存");
    await nextTick();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(wrapper.get("[role=alert]").text()).toContain("MCP 连接已保存");

    await vi.advanceTimersByTimeAsync(2_000);
    await nextTick();
    expect(wrapper.find("[role=alert]").exists()).toBe(false);
  });
});
