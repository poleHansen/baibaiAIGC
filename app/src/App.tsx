import { useEffect, useRef, useState } from "react";
import { DocumentCard } from "./components/DocumentCard";
import { HistoryCard } from "./components/HistoryCard";
import { ModelConfigCard } from "./components/ModelConfigCard";
import { ResultCard } from "./components/ResultCard";
import { useAppState } from "./hooks/useAppState";
import type { AppService } from "./lib/appService";
import type { HistoryDocumentSummary, HistoryRound, RoundProgress } from "./types/app";

type Props = {
  service: AppService;
  pickerLabel?: string;
};

function formatRuntimeStep(progress: RoundProgress | null, fallback: string): string {
  if (!progress) {
    return fallback;
  }
  if (progress.phase === "processing-chunk" && progress.currentChunk && progress.totalChunks) {
    return `正在执行第 ${progress.round} 轮，第 ${progress.currentChunk}/${progress.totalChunks} 块`;
  }
  if (progress.phase === "chunking-ready" && progress.totalChunks) {
    return `第 ${progress.round} 轮已切块，共 ${progress.totalChunks} 块，准备开始处理`;
  }
  if (progress.phase === "restoring-output") {
    return `第 ${progress.round} 轮已完成分块处理，正在合并输出`;
  }
  if (progress.phase === "chunk-complete" && progress.currentChunk && progress.totalChunks) {
    return `第 ${progress.round} 轮已完成第 ${progress.currentChunk}/${progress.totalChunks} 块`;
  }
  return fallback;
}

function describeDocumentProgress(nextRound: number | null, hasNextRound: boolean): string {
  if (hasNextRound && nextRound) {
    return `当前可执行第 ${nextRound} 轮。`;
  }
  return "当前文档已完成全部轮次。";
}

function describePromptProfile(promptProfile: "cn" | "en"): string {
  return promptProfile === "en" ? "英文单轮提示词" : "中文两轮提示词";
}

export function App({ service, pickerLabel }: Props) {
  const progressUnlistenRef = useRef<null | (() => void)>(null);
  const currentRunTokenRef = useRef<string | null>(null);
  const [pausing, setPausing] = useState(false);
  const {
    modelConfig,
    documentStatus,
    history,
    historyItems,
    historyPanelOpen,
    roundResult,
    progress,
    previewText,
    runtimeStep,
    notice,
    busy,
    error,
    setModelConfig,
    setDocumentStatus,
    setHistory,
    setHistoryItems,
    setHistoryPanelOpen,
    setRoundResult,
    setProgress,
    setPreviewText,
    setRuntimeStep,
    setNotice,
    setBusy,
    setError,
  } = useAppState();

  useEffect(() => {
    service.loadModelConfig()
      .then((config) => setModelConfig(config))
      .catch((appError: unknown) => setError(String(appError)));
  }, [service, setError, setModelConfig]);

  useEffect(() => {
    service.listDocumentHistories()
      .then((result) => setHistoryItems(result.items))
      .catch((appError: unknown) => setError(String(appError)));
  }, [service, setError, setHistoryItems]);

  useEffect(() => {
    return () => {
      progressUnlistenRef.current?.();
      progressUnlistenRef.current = null;
    };
  }, []);

  async function refreshDocumentState(sourcePath: string, config = modelConfig) {
    const [status, nextHistory] = await Promise.all([
      service.getDocumentStatus(sourcePath, config),
      service.getDocumentHistory(sourcePath),
    ]);
    setDocumentStatus(status);
    setHistory(nextHistory);
    return status;
  }

  async function refreshHistoryList() {
    const result = await service.listDocumentHistories();
    setHistoryItems(result.items);
    return result.items;
  }

  async function handleSelectHistory(item: HistoryDocumentSummary) {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep("正在载入历史文档");
      const status = await refreshDocumentState(item.sourcePath);
      setRoundResult(null);
      setPreviewText("");
      setNotice(`已切换到历史文档，${describeDocumentProgress(status.nextRound, status.hasNextRound)}`);
      setRuntimeStep(status.hasNextRound && status.nextRound ? `已载入历史文档，当前到第 ${status.nextRound} 轮` : "已载入历史文档，全部轮次已完成");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("载入历史文档失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteHistory(docId: string, fromRound?: number) {
    const actionLabel = fromRound ? `删除第 ${fromRound} 轮及之后历史` : "删除整条历史";
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep(`正在${actionLabel}`);
      const result = await service.deleteDocumentHistory(docId, fromRound);
      const items = await refreshHistoryList();
      if (documentStatus?.docId === docId) {
        if (result.removedDocument) {
          setDocumentStatus(null);
          setHistory(null);
          setRoundResult(null);
          setPreviewText("");
        } else {
          const matchedItem = items.find((item) => item.docId === docId);
          if (matchedItem) {
            await refreshDocumentState(matchedItem.sourcePath);
            setRoundResult(null);
            setPreviewText("");
          }
        }
      }
      const deletedText = result.deletedRounds.length ? `已删除轮次：${result.deletedRounds.join(", ")}` : "没有匹配到可删除的轮次";
      setNotice(result.removedDocument ? `历史已删除。${deletedText}` : `历史已更新。${deletedText}`);
      setRuntimeStep(result.removedDocument ? "历史删除完成" : "历史回滚完成");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep(`${actionLabel}失败`);
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveModelConfig() {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep("正在保存模型设置");
      const saved = await service.saveModelConfig(modelConfig);
      setModelConfig(saved);
      if (documentStatus) {
        await refreshDocumentState(documentStatus.sourcePath, saved);
      }
      setNotice(`模型设置已保存到本地，当前模式为${describePromptProfile(saved.promptProfile)}。`);
      setRuntimeStep("模型设置已保存");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("保存模型设置失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleTestConnection() {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep(modelConfig.offlineMode ? "离线模式无需测试远程接口" : "正在测试接口连通性");
      const result = await service.testModelConnection(modelConfig);
      setNotice(
        result.message
        + (result.apiType ? ` 类型：${result.apiType}` : "")
        + (result.endpoint ? ` 接口：${result.endpoint}` : ""),
      );
      setRuntimeStep(result.offlineMode ? "离线模式已确认" : "接口连通性测试成功");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("接口连通性测试失败");
    } finally {
      setBusy(false);
    }
  }

  async function handlePickFile() {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep("正在选择并读取文档");
      const picked = await service.pickInputFile();
      if (!picked) {
        setNotice("已取消选择文档。");
        setRuntimeStep("待命");
        return;
      }
      const status = await refreshDocumentState(picked.sourcePath);
      await refreshHistoryList();
      setHistoryPanelOpen(true);
      setRoundResult(null);
      setPreviewText("");
      setRuntimeStep(status.hasNextRound && status.nextRound ? `已载入文档，当前到第 ${status.nextRound} 轮` : "已载入文档，全部轮次已完成");
      setNotice(`已导入文档，当前使用${describePromptProfile(modelConfig.promptProfile)}，${describeDocumentProgress(status.nextRound, status.hasNextRound)}`);
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("读取文档失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleRunRound() {
    if (!documentStatus) {
      setNotice("请先导入一个 txt 或 docx 文档。");
      return;
    }
    if (!documentStatus.hasNextRound || documentStatus.isComplete || !documentStatus.nextRound) {
      setNotice("当前文档已完成全部轮次，如需重跑请先从历史记录回滚。");
      return;
    }
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setProgress(null);
      progressUnlistenRef.current?.();
      const runToken = await service.startRunRound(documentStatus.sourcePath, modelConfig);
      currentRunTokenRef.current = runToken;
      setPausing(false);
      progressUnlistenRef.current = await service.listenRoundProgress((nextProgress) => {
        setProgress(nextProgress);
        setRuntimeStep(formatRuntimeStep(nextProgress, "处理中"));
      }, runToken);
      setRuntimeStep(`准备执行第 ${documentStatus.nextRound} 轮`);
      setNotice(`本次运行将使用${describePromptProfile(modelConfig.promptProfile)}。`);
      const result = await service.awaitRunRound(documentStatus.sourcePath, modelConfig, runToken);
      progressUnlistenRef.current?.();
      progressUnlistenRef.current = null;
      setProgress(null);
      setRuntimeStep(`第 ${result.round} 轮处理中，正在读取预览`);
      setRoundResult(result);
      const preview = await service.readOutput(result.outputPath);
      setPreviewText(preview.text);
      setRuntimeStep(`第 ${result.round} 轮已完成，正在刷新历史`);
      const status = await refreshDocumentState(documentStatus.sourcePath);
      await refreshHistoryList();
      setHistoryPanelOpen(true);
      setRuntimeStep(status.hasNextRound && status.nextRound ? `第 ${result.round} 轮完成，下一步可执行第 ${status.nextRound} 轮` : `第 ${result.round} 轮完成，全部轮次已结束`);
      setNotice(status.hasNextRound ? `第 ${result.round} 轮已完成，可以继续导出或进入下一轮。` : `第 ${result.round} 轮已完成，当前文档的全部轮次已结束，可以直接导出。`);
    } catch (appError) {
      progressUnlistenRef.current?.();
      progressUnlistenRef.current = null;
      setProgress(null);
      const message = String(appError);
      if (/cancelled|已取消|取消/.test(message)) {
        setNotice("已暂停当前任务");
        setRuntimeStep("已暂停并完成中断存档");
      } else {
        setError(message);
        setRuntimeStep("执行轮次失败");
      }
    } finally {
      currentRunTokenRef.current = null;
      setPausing(false);
      setBusy(false);
    }
  }

  async function handlePauseRound() {
    const runToken = currentRunTokenRef.current;
    if (!runToken || !busy) {
      setNotice("当前没有可暂停的运行任务。");
      return;
    }
    try {
      setError("");
      setPausing(true);
      setRuntimeStep("正在请求暂停并触发中断存档");
      await service.cancelRunRound(runToken);
      setNotice("暂停请求已发送");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("暂停请求失败");
      setPausing(false);
    }
  }

  async function handleHistoryDownload(item: HistoryRound, targetFormat: "txt" | "docx") {
    if (!item.outputPath) {
      setNotice("当前历史记录没有可导出的输出路径。");
      return;
    }
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep(`正在导出第 ${item.round} 轮 ${targetFormat.toUpperCase()}`);
      const result = await service.exportRound(item.outputPath, targetFormat);
      setNotice(`第 ${item.round} 轮已导出 ${result.format.toUpperCase()}：${result.path}`);
      setRuntimeStep(`第 ${item.round} 轮导出完成`);
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep(`第 ${item.round} 轮导出失败`);
    } finally {
      setBusy(false);
    }
  }

  async function handleExport(targetFormat: "txt" | "docx") {
    if (!roundResult) {
      setNotice("请先执行至少一轮处理，再导出结果。");
      return;
    }
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep(`正在导出 ${targetFormat.toUpperCase()}`);
      const result = await service.exportRound(roundResult.outputPath, targetFormat);
      setNotice(`已导出 ${result.format.toUpperCase()}：${result.path}`);
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("导出失败");
    } finally {
      if (!error) {
        setRuntimeStep("导出完成");
      }
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <div className="hero-panel">
        <div>
          <p className="eyebrow">baibaiAIGC</p>
          <h1>超级超级好用的降AI神器！</h1>
          <p className="hero-copy">
            这是一个面向中文论文与技术文档的 Windows 桌面工作台。你可以配置模型、导入 txt 或 Word，逐轮执行改写，并在每轮结束后导出 txt 或 Word。
          </p>
        </div>
        {busy ? <span className="status-tag">{progress?.round ? `第 ${progress.round} 轮运行中` : "处理中"}</span> : <span className="status-tag idle">待命</span>}
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {notice ? <div className="notice-banner">{notice}</div> : null}

      <div className="runtime-log" aria-live="polite">
        <span className="runtime-log-label">运行步骤</span>
        <strong>{formatRuntimeStep(progress, runtimeStep)}</strong>
      </div>

      <section className="content-grid">
        <ModelConfigCard
          value={modelConfig}
          busy={busy}
          onChange={setModelConfig}
          onSave={handleSaveModelConfig}
          onTestConnection={handleTestConnection}
        />
        <DocumentCard
          value={documentStatus}
          busy={busy}
          onPickFile={handlePickFile}
          onRunRound={handleRunRound}
          onPauseRound={handlePauseRound}
          canPause={Boolean(documentStatus) && busy && Boolean(currentRunTokenRef.current) && !pausing}
          pickerLabel={pickerLabel}
        />
      </section>

      <HistoryCard
        currentDocId={documentStatus?.docId ?? null}
        currentHistory={history}
        items={historyItems}
        open={historyPanelOpen}
        busy={busy}
        onToggle={() => setHistoryPanelOpen(!historyPanelOpen)}
        onSelect={handleSelectHistory}
        onDelete={handleDeleteHistory}
        onDownload={handleHistoryDownload}
      />

      <ResultCard
        result={roundResult}
        previewText={previewText}
        busy={busy}
        onExportTxt={() => handleExport("txt")}
        onExportDocx={() => handleExport("docx")}
      />
    </main>
  );
}
