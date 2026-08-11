import { newQuickJSWASMModuleFromVariant, type QuickJSWASMModule } from "quickjs-emscripten-core";
import variant from "@jitl/quickjs-singlefile-browser-release-sync";

// Loading the WASM module is expensive, so cache the single instance for the
// life of the page. Contexts/runtimes created from it are cheap and short-lived
// (one per transform run), but the module itself is built once.
let modulePromise: Promise<QuickJSWASMModule> | null = null;

export function getQuickJSModule(): Promise<QuickJSWASMModule> {
  return (modulePromise ??= newQuickJSWASMModuleFromVariant(variant));
}
