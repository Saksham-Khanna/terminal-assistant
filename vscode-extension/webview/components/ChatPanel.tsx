import React, { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage, ToolCall, WsIncoming } from "../types";
import { useWebSocket, ConnectionStatus } from "../hooks/useWebSocket";
import { MessageBubble } from "./MessageBubble";
import { StatusBar } from "./StatusBar";
import { SessionPicker } from "./SessionPicker";

interface Props {
  backendUrl: string;
  token: string;
}

let msgCounter = 0;
function nextId(): string {
  return `msg-${Date.now()}-${++msgCounter}`;
}

export const ChatPanel: React.FC<Props> = ({ backendUrl, token }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [usageInfo, setUsageInfo] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const currentAgentMsgRef = useRef<string | null>(null);
  const pendingToolCalls = useRef<ToolCall[]>([]);

  const handleWsMessage = useCallback((msg: WsIncoming) => {
    switch (msg.type) {
      case "status":
        if (msg.data === "thinking") {
          setIsThinking(true);
          // Create a new agent message placeholder
          const agentId = nextId();
          currentAgentMsgRef.current = agentId;
          pendingToolCalls.current = [];
          setMessages((prev) => [
            ...prev,
            { id: agentId, role: "agent", content: "", timestamp: Date.now(), isStreaming: true, toolCalls: [] },
          ]);
        } else if (msg.data === "reset") {
          setMessages([]);
        } else if (msg.data.startsWith("loaded:")) {
          const sid = msg.data.replace("loaded:", "");
          setMessages([
            { id: nextId(), role: "agent", content: `*Session \`${sid}\` loaded.*`, timestamp: Date.now() },
          ]);
        } else if (msg.data.startsWith("saved:")) {
          const sid = msg.data.replace("saved:", "");
          setMessages((prev) => [
            ...prev,
            { id: nextId(), role: "agent", content: `*Session saved as \`${sid}\`.*`, timestamp: Date.now() },
          ]);
        }
        break;

      case "text":
        // Append text to current agent message
        if (currentAgentMsgRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAgentMsgRef.current
                ? { ...m, content: m.content + msg.data }
                : m
            )
          );
        }
        break;

      case "tool":
        // Add tool call to current agent message
        if (currentAgentMsgRef.current) {
          const tc: ToolCall = { name: msg.data.name, args: msg.data.args };
          pendingToolCalls.current.push(tc);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAgentMsgRef.current
                ? { ...m, toolCalls: [...pendingToolCalls.current] }
                : m
            )
          );
        }
        break;

      case "usage":
        setUsageInfo(typeof msg.data === "string" ? msg.data : JSON.stringify(msg.data));
        break;

      case "done":
        // Mark streaming complete
        if (currentAgentMsgRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAgentMsgRef.current
                ? { ...m, isStreaming: false }
                : m
            )
          );
          currentAgentMsgRef.current = null;
        }
        setIsThinking(false);
        break;

      case "error":
        if (currentAgentMsgRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAgentMsgRef.current
                ? { ...m, content: m.content + `\n\n**Error:** ${msg.data}`, isStreaming: false }
                : m
            )
          );
          currentAgentMsgRef.current = null;
        }
        setIsThinking(false);
        break;
    }
  }, []);

  const { status, sendChat, sendReset, sendLoadSession, sendSaveSession } = useWebSocket({
    url: backendUrl,
    token,
    onMessage: handleWsMessage,
  });

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isThinking) { return; }

    // Add user message
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: text, timestamp: Date.now() },
    ]);
    sendChat(text);
    setInput("");

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [input, isThinking, sendChat]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleReset = () => {
    sendReset();
    setMessages([]);
    setUsageInfo("");
  };

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 150) + "px";
  };

  return (
    <div className="chat-panel">
      <div className="chat-toolbar">
        <SessionPicker
          backendUrl={backendUrl}
          token={token}
          onSelectSession={sendLoadSession}
          onNewSession={handleReset}
          onSaveSession={sendSaveSession}
        />
        <StatusBar status={status} usage={usageInfo} />
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-icon">🤖</div>
            <p>Send a message to start coding with your agent.</p>
            <p className="chat-empty-hint">
              Try: "Read sample.py and explain what it does"
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <textarea
          ref={textareaRef}
          className="chat-input"
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder={isThinking ? "Agent is thinking…" : "Ask the agent… (Shift+Enter for new line)"}
          disabled={status !== "connected"}
          rows={1}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={!input.trim() || isThinking || status !== "connected"}
        >
          {isThinking ? "⏳" : "→"}
        </button>
      </div>
    </div>
  );
};
