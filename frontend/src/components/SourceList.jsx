import { getSourceHref, getSourceHost } from "../utils/sources";

export default function SourceList({ title, entries, keyPrefix }) {
  if (!Array.isArray(entries) || entries.length === 0) {
    return null;
  }

  return (
    <div className="block">
      <h3>{title}</h3>
      <ul className="source-list">
        {entries.map((entry) => (
          <li key={`${keyPrefix}-${entry.number}`} className="source-item">
            <a
              href={getSourceHref(entry.source)}
              target="_blank"
              rel="noopener noreferrer"
              className="source-card"
              title={entry.source.title || "来源链接"}
            >
              <span className="source-type">
                [{entry.number}] {entry.source.source_type || "source"}
              </span>
              <span className="source-title">{entry.source.title || "未命名来源"}</span>
              <span className="source-host">{getSourceHost(entry.source)}</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
