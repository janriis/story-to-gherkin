"""Short, local guidance for the Gherkin desktop application."""

import tkinter as tk
from tkinter import scrolledtext, ttk

from ui_layout import ACTION_BUTTON_WIDTH


_PAGES = (
    (
        "start",
        "Kom i gang",
        """1. Start Ollama på din computer, vælg en lokal model, og brug Kontrollér forbindelse.

2. Vælg Dansk eller English som scenariesprog.

3. Indsæt en user story i feltet, eller indlæs en UTF-8-tekstfil. Du kan skrive frit i én eller flere linjer; "Som ... vil jeg ... så ..." er ikke et krav. Beskriv gerne den forventede adfærd konkret.

4. Tilføj eventuelt testbasis eller acceptkriterier. Du kan skrive dem direkte eller indlæse .txt, .md, en tekstbaseret .pdf eller .docx. Scannede PDF-sider kræver OCR og kan ikke læses her.

5. Vælg en Promptkæde. Standard er klar til brug. Hvis du vil ændre prompts, så klik Redigér kæder og lav en kopi af Standard.

6. Klik Generér scenarier. Vis mellemresultater viser modellens rå første svar og eventuel reparation med Standard, eller hvert trins svar i en kæde. Gennemgå slutresultatet fagligt, og klik Gem .feature. Programmet validerer Gherkin-formatet, men kan ikke garantere, at alle krav er dækket.""",
    ),
    (
        "chains",
        "Promptkæder",
        """Standard er indbygget og skrivebeskyttet. Den kan bruges direkte, men ikke overskrives.

Sådan laver du din egen kæde:
1. Klik Redigér kæder i hovedvinduet.
2. Vælg Standard, klik Kopiér, og giv kopien et navn.
3. Redigér Systemprompt og Brugerprompt. Brug Tilføj trin for at lave en kæde med flere trin, og flyt trinnene til den ønskede rækkefølge.
4. Brug {{user_story}} og {{test_basis}} til at indsætte dine data. Fra trin 2 skal Brugerprompt indeholde {{previous_output}}, så den får forrige trins svar. {{language}} kan også bruges.
5. Redigér om nødvendigt Reparationsinstruktion. Den kan bruge {{validation_error}} og {{invalid_output}}.
6. Klik Gem kæde. Luk editoren, og vælg den nye kæde under Promptkæde i hovedvinduet.

Kæder er knyttet til det valgte scenariesprog. En dansk kæde vises ikke, når English er valgt, og omvendt. Kun det sidste trins svar valideres; ved fejl får modellen ét reparationsforsøg. Mellemresultaterne er rå model-svar og kan være ugyldige.""",
    ),
    (
        "problems",
        "Hvis noget driller",
        """Kun Standard i listen? Der er måske endnu ingen gemte kæder for det valgte sprog. Åbn Redigér kæder, klik Kopiér, giv kæden et navn, og klik Gem kæde. Hvis programmet viser en advarsel om kædefilen, skal filen rettes først.

Kan du ikke redigere Standard? Det er tilsigtet. Kopiér den først, og redigér kopien.

Ingen modeller eller forbindelsesfejl? Kontrollér, at Ollama kører lokalt, og brug Kontrollér forbindelse. Cloud-modeller kan ikke vælges.

Intet resultat at gemme? Modellen kan have svaret i ugyldigt Gherkin-format. Programmet forsøger én reparation og tillader kun at gemme et valideret resultat.

Fejllog: Se logs\\gherkin-errors.log i samme mappe som programmet. Den viser tidspunkt, handling, fejltype og kodeplacering, men gemmer ikke din user story, testbasis eller modellens svar. De ældste logposter roteres automatisk.

Mangler et krav fra testbasis i scenarierne? Validering kontrollerer formatet, ikke faglig fuldstændighed. Gennemgå resultatet, og gør kravet tydeligere i testbasis eller prompten før en ny generering.""",
    ),
)


class GherkinHelp(tk.Toplevel):
    """Show non-modal, read-only help without changing user data."""

    def __init__(self, parent: tk.Misc, initial_page: str = "start") -> None:
        super().__init__(parent)
        self.title("Hjælp – Gherkin fra user story")
        self.geometry("790x570")
        self.minsize(600, 420)
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        notebook = ttk.Notebook(frame)
        notebook.pack(fill="both", expand=True)
        pages: dict[str, ttk.Frame] = {}
        for key, title, content in _PAGES:
            tab = ttk.Frame(notebook, padding=8)
            notebook.add(tab, text=title)
            guide = scrolledtext.ScrolledText(
                tab, wrap="word", padx=10, pady=10, width=1, height=1,
            )
            guide.pack(fill="both", expand=True)
            guide.insert("1.0", content)
            guide.configure(state="disabled")
            pages[key] = tab
        notebook.select(pages.get(initial_page, pages["start"]))
        ttk.Button(
            frame, text="Luk", command=self.destroy, width=ACTION_BUTTON_WIDTH,
        ).pack(anchor="e", pady=(10, 0))
