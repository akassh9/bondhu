import { create } from "zustand";

export const useAppStore = create((set) => ({
  threadId: null,
  settingId: null,
  workflowId: null,
  workflowRunId: null,
  setThreadId: (threadId) => set({ threadId }),
  setSettingId: (settingId) => set({ settingId }),
  setWorkflowId: (workflowId) => set({ workflowId }),
  setWorkflowRunId: (workflowRunId) => set({ workflowRunId }),
}));
