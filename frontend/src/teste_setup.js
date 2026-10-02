import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// sem "globals" no vitest, a Testing Library não limpa sozinha entre testes
afterEach(cleanup);
