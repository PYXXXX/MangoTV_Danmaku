import { create } from "zustand";

export type AdminPage = "activity" | "ops" | "settings" | "machine" | "logs";

interface UiState {
  page: AdminPage;
  selectedRoundId: string | null;
  resultType: "rough" | "precise";
  setPage: (page: AdminPage) => void;
  setSelectedRoundId: (roundId: string | null) => void;
  setResultType: (type: "rough" | "precise") => void;
}

export const useUiStore = create<UiState>((set) => ({
  page: "activity",
  selectedRoundId: null,
  resultType: "rough",
  setPage: (page) => set({ page }),
  setSelectedRoundId: (selectedRoundId) => set({ selectedRoundId }),
  setResultType: (resultType) => set({ resultType })
}));
