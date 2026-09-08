import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";
import { ToolCallCard } from "./ToolCallCard";

interface Props {
  message: ChatMessage;
}

export const MessageBubble: React.FC<Props> = ({ message }) => {
  const isUser = message.role === "user";

  return (
    <div className={`message-bubble ${isUser ? "message-user" : "message-agent"}`}>
      <div className="message-role">
        {isUser ? "You" : "Agent"}
      </div>
      <div className="message-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ className, children, ...props }) {
              const isInline = !className;
              if (isInline) {
                return <code className="inline-code" {...props}>{children}</code>;
              }
              const language = className?.replace("language-", "") || "";
              return (
                <div className="code-block">
                  <div className="code-block-header">
                    <span>{language}</span>
                  </div>
                  <pre><code className={className} {...props}>{children}</code></pre>
                </div>
              );
            },
            table({ children, ...props }) {
              return <table className="markdown-table" {...props}>{children}</table>;
            },
          }}
        >
          {message.content}
        </ReactMarkdown>
      </div>
      {message.toolCalls && message.toolCalls.length > 0 && (
        <div className="message-tool-calls">
          {message.toolCalls.map((tc, i) => (
            <ToolCallCard key={i} toolCall={tc} />
          ))}
        </div>
      )}
      {message.isStreaming && (
        <span className="streaming-cursor">▊</span>
      )}
    </div>
  );
};
