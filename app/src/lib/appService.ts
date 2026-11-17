import type {
  DeleteHistoryResult,
  DocumentHistory,
  DocumentStatus,
  ExportResult,
  FetchModelsResult,
  HistoryListResponse,
  ModelConfig,
  OutputPreview,
  ProgressPreview,
  RoundProgress,
  RoundResult,
  RunExecutionOptions,
  TestConnectionResult,
} from "../types/app";

export type PickedDocument = {
  sourcePath: string;
  filename: string;
  displayName: string;
};

export interface AppService {
  loadModelConfig(): Promise<ModelConfig>;
  saveModelConfig(config: ModelConfig): Promise<ModelConfig>;
  testModelConnection(config: ModelConfig): Promise<TestConnectionResult>;
  fetchModels(config: ModelConfig): Promise<FetchModelsResult>;
  pickInputFile(): Promise<PickedDocument | null>;
  getDocumentStatus(sourcePath: string, modelConfig: ModelConfig): Promise<DocumentStatus>;
  getDocumentHistory(sourcePath: string): Promise<DocumentHistory>;
  listDocumentHistories(): Promise<HistoryListResponse>;
  deleteDocumentHistory(docId: string, fromRound?: number): Promise<DeleteHistoryResult>;
  requestStop(sourcePath: string, modelConfig: ModelConfig, runToken?: string | null): Promise<DocumentStatus>;
  startRunRound(sourcePath: string, modelConfig: ModelConfig, executionOptions?: RunExecutionOptions | null): Promise<string | null>;
  awaitRunRound(sourcePath: string, modelConfig: ModelConfig, runToken?: string | null, executionOptions?: RunExecutionOptions | null): Promise<RoundResult>;
  listenRoundProgress(onProgress: (payload: RoundProgress) => void, runToken?: string | null): Promise<() => void>;
  readOutput(outputPath: string): Promise<{ path: string; text: string }>;
  readOutputPreview(outputPath: string, manifestPath: string): Promise<OutputPreview>;
  readProgressPreview(manifestPath: string): Promise<ProgressPreview>;
  readSourcePreview(inputPath: string, manifestPath: string, promptProfile: "cn" | "en"): Promise<OutputPreview>;
  exportRound(
    outputPath: string,
    targetFormat: "txt" | "docx",
    sourcePath?: string,
    docxOutputPath?: string,
    manifestPath?: string,
  ): Promise<ExportResult>;
}
