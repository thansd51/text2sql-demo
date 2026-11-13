import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { setAccessKey } from "../api";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  setAccessKey("");
});
