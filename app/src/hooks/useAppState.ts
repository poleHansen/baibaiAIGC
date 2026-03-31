import { create } from "zustand";
import type { DocumentHistory, DocumentStatus, HistoryDocumentSummary, ModelConfig, RoundProgress, RoundResult } from "../types/app";

const defaultModelConfig: ModelConfig = {
  baseUrl: "",
  apiKey: "",
  model: "",
  apiType: "responses",
  temperature: 0.7,
  offlineMode: false,
  promptProfile: "cn",
};

type AppState = {
  modelConfig: ModelConfig;
  documentStatus: DocumentStatus | null;
  history: DocumentHistory | null;
  historyItems: HistoryDocumentSummary[];
  historyPanelOpen: boolean;
  roundResult: RoundResult | null;
  progress: RoundProgress | null;
  previewText: string;
  runtimeStep: string;
  notice: string;
  busy: boolean;
  error: string;
  setModelConfig: (config: ModelConfig) => void;
  setDocumentStatus: (status: DocumentStatus | null) => void;
  setHistory: (history: DocumentHistory | null) => void;
  setHistoryItems: (items: HistoryDocumentSummary[]) => void;
  setHistoryPanelOpen: (open: boolean) => void;
  setRoundResult: (result: RoundResult | null) => void;
  setProgress: (progress: RoundProgress | null) => void;
  setPreviewText: (text: string) => void;
  setRuntimeStep: (text: string) => void;
  setNotice: (notice: string) => void;
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
};

export const useAppState = create<AppState>((set) => ({
  modelConfig: defaultModelConfig,
  documentStatus: null,
  history: null,
  historyItems: [],
  historyPanelOpen: false,
  roundResult: null,
  progress: null,
  previewText: "",
  runtimeStep: "待命",
  notice: "",
  busy: false,
  error: "",
  setModelConfig: (modelConfig) => set({ modelConfig }),
  setDocumentStatus: (documentStatus) => set({ documentStatus }),
  setHistory: (history) => set({ history }),
  setHistoryItems: (historyItems) => set({ historyItems }),
  setHistoryPanelOpen: (historyPanelOpen) => set({ historyPanelOpen }),
  setRoundResult: (roundResult) => set({ roundResult }),
  setProgress: (progress) => set({ progress }),
  setPreviewText: (previewText) => set({ previewText }),
  setRuntimeStep: (runtimeStep) => set({ runtimeStep }),
  setNotice: (notice) => set({ notice }),
  setBusy: (busy) => set({ busy }),
  setError: (error) => set({ error }),
}));
