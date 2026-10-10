import { TypeSafeClient } from "@typesafe-ai/sdk";
import { questionsFor } from "./questions.ts";
import type { Config, ReviewerClient, ReviewResponse } from "./contracts.ts";
export function createJevClient(
  config: Config,
  select: typeof questionsFor = questionsFor,
): ReviewerClient {
  // Lazy: off/local neither require credentials nor instantiate the network client.
  return async (snapshot, signal): Promise<ReviewResponse> => {
    const client = new TypeSafeClient({
      apiKey: process.env.TYPESAFE_API_KEY,
      baseURL: "https://api.typesafe.ai",
      logLevel: "off",
      retry: { maxRetries: 0 },
      timeout: config.deadlineMs,
    });
    const { questions, references } = select(snapshot);
    const response = await client.systemOne(
      {
        model: config.model,
        state: JSON.parse(JSON.stringify(snapshot)),
        questions,
      },
      { signal, timeout: config.deadlineMs, retry: { maxRetries: 0 } },
    );
    return {
      model: response.model,
      usage: response.usage,
      judgments: Object.entries(references).map(([key, ref]) => {
        const answer = response.answers[key];
        if (
          !answer ||
          answer.type !== "choice" ||
          !["problem", "useful", "uncertain"].includes(answer.choice)
        )
          throw new Error("Respuesta inválida.");
        return {
          ...ref,
          choice: answer.choice as "problem" | "useful" | "uncertain",
          confidence: answer.confidence,
          probabilities: answer.probabilities,
        };
      }),
    };
  };
}
