import type { DocumentHistory, HistoryDocumentSummary, HistoryRevision, HistoryRound } from "../types/app";

type Props = {
  currentDocId: string | null;
  currentHistory: DocumentHistory | null;
  items: HistoryDocumentSummary[];
  open: boolean;
  busy: boolean;
  embedded?: boolean;
  onToggle: () => void;
  onSelect: (item: HistoryDocumentSummary) => void;
  onDelete: (docId: string, fromRound?: number) => void;
  onDownload: (item: HistoryRound | HistoryRevision, format: "txt" | "docx", sourcePath: string) => void;
  onPreview: (item: HistoryRound | HistoryRevision, sourcePath: string) => void;
};

function formatTimestamp(value: string): string {
  if (!value) {
    return "时间未知";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function buildDisplayNameMap(items: HistoryDocumentSummary[], currentHistory: DocumentHistory | null, currentDocId: string | null): Map<string, string> {
  const usageCount = new Map<string, number>();
  const displayMap = new Map<string, string>();

  const orderedItems = items.map((item) => {
    const rawName = item.displayName || item.originPath || item.sourcePath || item.docId;
    return { docId: item.docId, rawName };
  });

  if (currentHistory && currentDocId && !orderedItems.some((item) => item.docId === currentDocId)) {
    orderedItems.unshift({
      docId: currentDocId,
      rawName: currentHistory.displayName || currentHistory.sourcePath || currentHistory.docId,
    });
  }

  orderedItems.forEach((item) => {
    const nextIndex = usageCount.get(item.rawName) ?? 0;
    usageCount.set(item.rawName, nextIndex + 1);
    displayMap.set(item.docId, nextIndex === 0 ? item.rawName : `${item.rawName}（${nextIndex}）`);
  });

  return displayMap;
}

function formatNextRound(completedRounds: number[]): string {
  const filtered = completedRounds.filter((round) => round >= 1 && round <= 2);
  if (filtered.length >= 2) {
    return "已完成";
  }
  if (!filtered.length) {
    return "1";
  }
  return String(Math.max(...filtered) + 1);
}

function describeLifecycleStatus(status: HistoryRound["status"] | HistoryRevision["status"]): string {
  if (status === "completed") {
    return "已完成";
  }
  if (status === "interrupted") {
    return "中断";
  }
  return "处理中";
}

function renderVersionActions(
  item: HistoryRound | HistoryRevision,
  busy: boolean,
  sourcePath: string,
  onDownload: (item: HistoryRound | HistoryRevision, format: "txt" | "docx", sourcePath: string) => void,
  onPreview: (item: HistoryRound | HistoryRevision, sourcePath: string) => void,
) {
  return (
    <div className="button-row">
      <button className="secondary-button" onClick={() => onPreview(item, sourcePath)} disabled={busy || !item.outputPath || !item.manifestPath}>
        预览并选择
      </button>
      <button className="secondary-button" onClick={() => onDownload(item, "txt", sourcePath)} disabled={busy || !item.outputPath}>
        下载 TXT
      </button>
      <button className="primary-button" onClick={() => onDownload(item, "docx", sourcePath)} disabled={busy || !item.outputPath}>
        下载 Word
      </button>
    </div>
  );
}

function renderLifecycleMeta(item: HistoryRound | HistoryRevision) {
  return (
    <>
      <div className="history-metrics">
        <span>状态 {describeLifecycleStatus(item.status)}</span>
        <span>进度 {item.totalChunkCount ? `${item.completedChunkCount}/${item.totalChunkCount}` : "-"}</span>
        <span>输入块数 {item.inputSegmentCount ?? "-"}</span>
        <span>输出块数 {item.outputSegmentCount ?? "-"}</span>
      </div>
      {item.lastError ? (
        <div className="path-box compact-box">
          <span>中断原因</span>
          <strong>{item.lastError}</strong>
        </div>
      ) : null}
      {item.stopReason ? (
        <div className="path-box compact-box">
          <span>停止说明</span>
          <strong>{item.stopReason}</strong>
        </div>
      ) : null}
      {item.canResume ? (
        <div className="path-box compact-box">
          <span>继续续跑</span>
          <strong>切换到此文档后可从当前断点继续执行</strong>
        </div>
      ) : null}
    </>
  );
}

export function HistoryCard({
  currentDocId,
  currentHistory,
  items,
  open,
  busy,
  embedded = false,
  onToggle,
  onSelect,
  onDelete,
  onDownload,
  onPreview,
}: Props) {
  const displayNameMap = buildDisplayNameMap(items, currentHistory, currentDocId);

  return (
    <section className={`${embedded ? "section-stack history-card history-card-embedded" : "glass-card section-stack history-card"}`}>
      <div className="section-header">
        <div>
          <h2>历史记录</h2>
          <p>显示已处理的文档、轮次结果与修订版，并支持重新打开预览选择段落。</p>
        </div>
        <button className="secondary-button history-toggle" onClick={onToggle} disabled={busy}>
          {open ? "收起历史记录" : `查看历史记录${items.length ? ` (${items.length})` : ""}`}
        </button>
      </div>
      {open ? (
        items.length ? (
          <div className="history-panel-scroll">
            <div className="history-list history-document-list">
              {items.map((item) => {
                const activeRounds = currentDocId === item.docId && currentHistory?.rounds.length ? currentHistory.rounds : item.rounds;
                const isActive = currentDocId === item.docId;
                const displayName = displayNameMap.get(item.docId) || item.displayName || item.originPath || item.sourcePath || item.docId;
                return (
                  <article key={item.docId} className={`history-item history-document ${isActive ? "active" : ""}`}>
                    <div className="history-item-head history-document-head">
                      <div>
                        <strong>{displayName}</strong>
                        <span>{item.lastTimestamp ? `最近更新 ${formatTimestamp(item.lastTimestamp)}` : "暂无时间"}</span>
                      </div>
                      <span className="pill">已完成 {item.completedRounds.length} 轮</span>
                    </div>
                    <div className="history-metrics">
                      <span>当前文档 {isActive ? "已加载" : "未加载"}</span>
                      <span>下一轮 {formatNextRound(item.completedRounds)}</span>
                    </div>
                    <div className="path-box compact-box">
                      <span>文档路径</span>
                      <strong>{item.originPath || item.sourcePath}</strong>
                    </div>
                    <div className="button-row history-document-actions">
                      <button className="secondary-button" onClick={() => onSelect(item)} disabled={busy}>
                        {isActive ? "重新加载" : "切换到此文档"}
                      </button>
                      <button className="secondary-button danger-button" onClick={() => onDelete(item.docId)} disabled={busy}>
                        删除文档及全部文件
                      </button>
                    </div>
                    {activeRounds.length ? (
                      <div className="history-round-list">
                        {activeRounds.map((roundItem) => (
                          <article key={`${item.docId}-${roundItem.round}`} className="history-item history-round-item">
                            <div className="history-item-head">
                              <strong>第 {roundItem.round} 轮</strong>
                              <span>{formatTimestamp(roundItem.timestamp)}</span>
                            </div>
                            {renderLifecycleMeta(roundItem)}
                            <div className="history-metrics">
                              <span>修订版 {roundItem.revisions.length}</span>
                            </div>
                            <div className="path-box compact-box">
                              <span>输出路径</span>
                              <strong>{roundItem.outputPath || "暂无"}</strong>
                            </div>
                            {renderVersionActions(roundItem, busy, item.sourcePath, onDownload, onPreview)}
                            <div className="button-row">
                              <button
                                className="secondary-button danger-button"
                                onClick={() => onDelete(item.docId, roundItem.round)}
                                disabled={busy}
                              >
                                从本轮重新跑
                              </button>
                            </div>
                            {roundItem.revisions.length ? (
                              <div className="history-revision-list">
                                {roundItem.revisions.map((revision) => (
                                  <article
                                    key={`${item.docId}-${roundItem.round}-rev-${revision.revisionNumber}`}
                                    className="history-item history-revision-item"
                                  >
                                    <div className="history-item-head">
                                      <strong>第 {roundItem.round} 轮 / 修订 {revision.revisionNumber}</strong>
                                      <span>{formatTimestamp(revision.timestamp)}</span>
                                    </div>
                                    {renderLifecycleMeta(revision)}
                                    <div className="history-metrics">
                                      <span>已选段落 {revision.targetParagraphIndexes.length}</span>
                                    </div>
                                    <div className="path-box compact-box">
                                      <span>输出路径</span>
                                      <strong>{revision.outputPath || "暂无"}</strong>
                                    </div>
                                    {renderVersionActions(revision, busy, item.sourcePath, onDownload, onPreview)}
                                  </article>
                                ))}
                              </div>
                            ) : null}
                          </article>
                        ))}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="empty-state history-empty">
            <strong>还没有历史记录</strong>
            <p>执行过的文档会显示在这里，之后可以直接切换回来继续处理。</p>
          </div>
        )
      ) : (
        <div className="empty-state history-empty">
          <strong>历史记录已收起</strong>
          <p>点击右上角按钮查看之前处理过的文档和各轮输出。</p>
        </div>
      )}
    </section>
  );
}
