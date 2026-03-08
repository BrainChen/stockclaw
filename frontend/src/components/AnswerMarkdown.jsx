import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getNodeText } from "../utils/answerText";

export default function AnswerMarkdown({ text }) {
  return (
    <article className="answer-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, ...props }) => {
            const linkText = getNodeText(children).trim();
            const isCitation = /^\d{1,3}$/.test(linkText);
            if (isCitation) {
              return (
                <a
                  {...props}
                  className="citation-link"
                  target="_blank"
                  rel="noopener noreferrer"
                  title={`查看引用 [${linkText}]`}
                >
                  [{linkText}]
                </a>
              );
            }
            return (
              <a
                {...props}
                className="answer-link"
                target="_blank"
                rel="noopener noreferrer"
              >
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </article>
  );
}
