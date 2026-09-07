// Advisory-only client-side preview (UX-02: "live classification"). This is
// never the source of truth - the server re-validates and canonicalizes
// independently (app/security/targets.py) at job creation, and its response
// (or 422 detail) is what actually drives the UI. This just gives the user
// immediate feedback while typing, using the same shape of rules.
import type { TargetType } from "../../api/types";

export interface TargetPreview {
  targetType: TargetType | "invalid" | "empty";
  message: string;
}

const IPV4 = /^(\d{1,3}\.){3}\d{1,3}$/;

export function classifyPreview(rawInput: string): TargetPreview {
  const trimmed = rawInput.trim();
  if (!trimmed) {
    return { targetType: "empty", message: "" };
  }
  if (/:\/\//.test(trimmed)) {
    return { targetType: "invalid", message: "Must not include a URL scheme." };
  }
  if (trimmed.includes("@")) {
    return { targetType: "invalid", message: "Must not include credentials." };
  }
  if (trimmed.includes("*")) {
    return { targetType: "invalid", message: "Wildcard targets are not supported." };
  }
  if (trimmed.includes("/")) {
    return { targetType: "cidr", message: "Looks like a CIDR block." };
  }
  if (IPV4.test(trimmed) || trimmed.includes(":")) {
    return { targetType: "ip", message: "Looks like an IP address." };
  }
  if (/^[a-zA-Z0-9.-]+\.[a-zA-Z0-9-]+$/.test(trimmed)) {
    return { targetType: "domain", message: "Looks like a domain." };
  }
  if (trimmed.length < 2 || trimmed.length > 120) {
    return { targetType: "invalid", message: "Too short or too long to be a valid target." };
  }
  return {
    targetType: "organization",
    message: "Looks like an organization name - not assessable until release 1.1.",
  };
}
