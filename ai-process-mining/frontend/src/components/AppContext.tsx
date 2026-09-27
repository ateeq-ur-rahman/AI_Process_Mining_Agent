import { createContext, useContext } from "react";

export type DrillTarget =
  | { kind: "case"; caseId: string }
  | { kind: "events"; title: string; activity?: string; source?: string; target?: string; resource?: string }
  | { kind: "variant"; variantId: string; trace: string };

export interface AppCtx {
  datasetId: string | null;
  setDatasetId: (id: string | null) => void;
  drill: (t: DrillTarget) => void;
  refreshDatasets: () => void;
}

export const AppContext = createContext<AppCtx>({
  datasetId: null, setDatasetId: () => {}, drill: () => {}, refreshDatasets: () => {},
});
export const useApp = () => useContext(AppContext);
