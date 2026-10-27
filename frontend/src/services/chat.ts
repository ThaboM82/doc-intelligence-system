import api from "./api";

export interface ChatRequest {
  message: string;
}

export interface ChatResponse {
  response: string;
}

export const ChatService = {
  sendMessage: (
    message: string
  ) =>
    api<ChatResponse>("/chat", {
      method: "POST",

      body: JSON.stringify({
        message,
      }),
    }),
};