import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from datetime import datetime


# --- Style vert sapin / doré ---
st.set_page_config(page_title="Simulateur fiscal immobilier", page_icon="🏠", layout="wide")
st.markdown("""
    <style>
    .stApp {
        background-color: #0b3d2e;
        color: #f5f2e7;
        font-family: 'Georgia', serif;
    }
    h1, h2, h3 {
        color: #d4af37;
        text-align: center;
    }
    .stButton>button {
        background-color: #d4af37;
        color: #0b3d2e;
        border-radius: 10px;
        border: none;
        padding: 0.6em 1.2em;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #b8972b;
        color: white;
    }
    .stNumberInput label, .stTextInput label, .stSelectbox label {
        color: #ffffff !important;
        font-weight: bold;
    }
    /* Amélioration de la lisibilité des st.info et st.warning */
    .stAlert {
        background-color: rgba(255, 255, 255, 0.95) !important;
    }
    .stAlert p, .stAlert div {
        color: #1e1e1e !important;
        font-weight: 500;
    }
    /* Tooltip personnalisé */
    .tooltip-container {
        display: inline-block;
        margin-left: 8px;
        position: relative;
    }
    .tooltip-icon {
        display: inline-block;
        width: 18px;
        height: 18px;
        background-color: #d4af37;
        color: #0b3d2e;
        border-radius: 50%;
        text-align: center;
        line-height: 18px;
        font-size: 12px;
        font-weight: bold;
        cursor: help;
    }
    .tooltip-text {
        visibility: hidden;
        width: 300px;
        background-color: #f5f2e7;
        color: #0b3d2e;
        text-align: left;
        border-radius: 6px;
        padding: 10px;
        position: absolute;
        z-index: 1000;
        bottom: 125%;
        left: 50%;
        margin-left: -150px;
        opacity: 0;
        transition: opacity 0.3s;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        font-size: 13px;
        line-height: 1.4;
    }
    .tooltip-text::after {
        content: "";
        position: absolute;
        top: 100%;
        left: 50%;
        margin-left: -5px;
        border-width: 5px;
        border-style: solid;
        border-color: #f5f2e7 transparent transparent transparent;
    }
    .tooltip-container:hover .tooltip-text {
        visibility: visible;
        opacity: 1;
    }
    </style>
""", unsafe_allow_html=True)

# --- Barème progressif 2025 ---
bareme = [
    (0, 11497, 0.00),
    (11498, 29315, 0.11),
    (29316, 83823, 0.30),
    (83824, 180294, 0.41),
    (180295, float("inf"), 0.45),
]

def impot_progressif(revenu_imposable, parts=1):
    revenu_par_part = revenu_imposable / parts
    impots = 0
    details = []
    for bas, haut, taux in bareme:
        if revenu_par_part > bas:
            tranche_imposable = min(revenu_par_part, haut) - bas
            impot_tranche = tranche_imposable * taux
            impots += impot_tranche
            details.append((bas, haut, taux, tranche_imposable, impot_tranche))
        else:
            break
    return impots * parts, details

# --- Calcul intérêts réels sur 12 mois ---
def calcul_interets_annuels(capital, taux_annuel, duree_annees):
    n_mois = duree_annees * 12
    taux_mensuel = taux_annuel / 100 / 12
    mensualite = capital * (taux_mensuel / (1 - (1 + taux_mensuel) ** -n_mois))
    interets_annuels = 0
    capital_restant = capital
    for _ in range(12):
        interet_mois = capital_restant * taux_mensuel
        interets_annuels += interet_mois
        amortissement_mois = mensualite - interet_mois
        capital_restant -= amortissement_mois
    return interets_annuels, mensualite

# --- Calcul revenu foncier ou BIC ---
def calcul_revenu_foncier(loyers, charges_classiques, interets_emprunt, assurance_emprunteur, 
                          type_loc, regime, amortissement_total=0):
    revenu_brut = loyers
    total_charges_pret = interets_emprunt + assurance_emprunteur
    
    if regime.startswith("Micro"):
        abattement = 30 if type_loc == "Nue" else 50
        revenu_imposable = revenu_brut * (1 - abattement / 100)
        return {
            "revenu_brut": revenu_brut,
            "abattement_pct": abattement,
            "revenu_imposable": revenu_imposable,
            "charges_classiques": 0,
            "interets": interets_emprunt,
            "assurance_pret": assurance_emprunteur,
            "amortissement_total": 0,
            "amortissement_deductible": 0,
            "amortissement_non_deductible": 0,
            "revenu_apres_interets": revenu_brut,
            "revenu_apres_charges": revenu_brut,
            "revenu_avant_amortissement": revenu_brut,
            "deficit_global": 0,
            "deficit_interets": 0,
        }
    else:
        # Régime réel
        revenu_apres_interets = revenu_brut - total_charges_pret
        deficit_interets = max(0, total_charges_pret - revenu_brut)
        revenu_apres_charges = revenu_apres_interets - charges_classiques
        
        # Pour location nue : déficit foncier classique
        if type_loc == "Nue":
            # Déficit imputable limité à 10 700 € (charges hors intérêts)
            # Les intérêts créent un déficit reportable séparément
            deficit_charges_seules = max(0, charges_classiques - revenu_apres_interets)
            deficit_global = min(deficit_charges_seules, 10700)
            assiette_imposable = max(0, revenu_apres_charges)
            
            return {
                "revenu_brut": revenu_brut,
                "abattement_pct": 0,
                "revenu_imposable": assiette_imposable,
                "charges_classiques": charges_classiques,
                "interets": interets_emprunt,
                "assurance_pret": assurance_emprunteur,
                "amortissement_total": 0,
                "amortissement_deductible": 0,
                "amortissement_non_deductible": 0,
                "revenu_apres_interets": revenu_apres_interets,
                "revenu_apres_charges": revenu_apres_charges,
                "revenu_avant_amortissement": revenu_apres_charges,
                "deficit_global": deficit_global,
                "deficit_interets": deficit_interets,
            }
        
        # Pour location meublée : amortissement avec limitation Art. 39 C
        else:
            revenu_avant_amortissement = revenu_apres_charges
            
            # Article 39 C du CGI : l'amortissement ne peut excéder
            # la différence entre loyers et autres charges
            plafond_amortissement = max(0, revenu_avant_amortissement)
            amortissement_deductible = min(amortissement_total, plafond_amortissement)
            amortissement_non_deductible = amortissement_total - amortissement_deductible
            
            revenu_apres_amortissement = revenu_avant_amortissement - amortissement_deductible
            assiette_imposable = max(0, revenu_apres_amortissement)
            
            return {
                "revenu_brut": revenu_brut,
                "abattement_pct": 0,
                "revenu_imposable": assiette_imposable,
                "charges_classiques": charges_classiques,
                "interets": interets_emprunt,
                "assurance_pret": assurance_emprunteur,
                "amortissement_total": amortissement_total,
                "amortissement_deductible": amortissement_deductible,
                "amortissement_non_deductible": amortissement_non_deductible,
                "revenu_apres_interets": revenu_apres_interets,
                "revenu_apres_charges": revenu_apres_charges,
                "revenu_avant_amortissement": revenu_avant_amortissement,
                "deficit_global": 0,
                "deficit_interets": 0,
            }

# --- Interface ---
st.title("🏠 Simulateur fiscal immobilier et rendement")

st.info("""ℹ️ Ce simulateur calcule la fiscalité de la **première année** d'investissement. Les intérêts d'emprunt diminuent progressivement les années suivantes.
""")

RFR = st.number_input("Revenu Fiscal de Référence (RFR)", value=50000)
st.caption("💡 Montant indiqué sur votre avis d'imposition. Il s'agit du revenu net imposable après abattements et déductions.")

parts = st.number_input("Nombre de parts fiscales", value=1)
st.caption("💡 1 part pour célibataire, 2 parts pour couple, +0,5 part par enfant à charge (1 part entière à partir du 3ème).")

loyers = st.number_input("Revenus locatifs annuels (€)", value=10000)
st.caption("💡 Montant total des loyers perçus sur l'année (hors charges). Pour un loyer mensuel de 800€, indiquez 9 600€.")

st.subheader("🏘️ Type de bien")
type_bien = st.selectbox("Type de bien immobilier", ["Appartement", "Maison individuelle"])
st.caption("💡 Appartement : terrain négligeable. Maison : terrain à déduire (non amortissable).")

prix_bien = st.number_input("Prix d'achat du bien (€)", value=200000)
st.caption("💡 Prix d'acquisition hors frais de notaire et agence")

type_achat = st.selectbox("Type d'achat", ["Ancien", "Neuf"])
taux_notaire = 0.08 if type_achat == "Ancien" else 0.03
frais_notaire = st.number_input("Frais de notaire (€)", value=int(prix_bien * taux_notaire))
st.caption(f"💡 Environ {taux_notaire*100:.0f}% du prix d'achat pour un bien {type_achat.lower()}")

valeur_terrain = 0
valeur_amortissable = prix_bien

if type_bien == "Maison individuelle":
    st.warning("⚠️ Pour une maison, le terrain n'est pas amortissable (LMNP)")
    valeur_terrain = st.number_input("Valeur du terrain (€)", value=int(prix_bien * 0.15))
    st.caption("💡 Généralement 10-25% du prix total")
    valeur_amortissable = prix_bien - valeur_terrain
    st.info(f"💡 Valeur amortissable (bâti) : {valeur_amortissable:,.0f} €")
else:
    st.info("ℹ️ Pour un appartement, la totalité du prix est amortissable (terrain négligeable)")

st.subheader("🛋️ Amortissement LMNP (location meublée au réel)")
with st.expander("Paramètres d'amortissement"):
    st.warning("⚠️ Ce calcul est simplifié pour vous donner une première estimation. La fiscalité du LMNP est complexe et nécessite l'accompagnement d'un expert-comptable pour une optimisation précise (décomposition par composants, stratégie pluriannuelle, application de l'article 39 C du CGI, etc.).")
    
    duree_amortissement_bati = st.number_input("Durée d'amortissement du bâti (années)", 
                                                value=25, min_value=20, max_value=40)
    st.caption("💡 Généralement entre 25 et 30 ans")
    
    valeur_mobilier = st.number_input("Valeur du mobilier (€)", value=10000)
    st.caption("💡 Coût d'ameublement du logement")
    
    duree_amortissement_mobilier = st.number_input("Durée d'amortissement du mobilier (années)", 
                                                    value=7, min_value=5, max_value=10)
    st.caption("💡 Généralement entre 5 et 10 ans")

# Calcul des amortissements
amortissement_bati = valeur_amortissable / duree_amortissement_bati
amortissement_mobilier = valeur_mobilier / duree_amortissement_mobilier
amortissement_total = amortissement_bati + amortissement_mobilier

st.write(f"💡 Amortissement annuel bâti : {amortissement_bati:.2f} €")
st.write(f"💡 Amortissement annuel mobilier : {amortissement_mobilier:.2f} €")
st.write(f"💡 **Amortissement total calculé : {amortissement_total:.2f} €**")

st.subheader("💼 Charges déductibles (réelles)")
taxe_fonciere = st.number_input("Taxe foncière annuelle (€)", value=2000)
st.caption("💡 Montant annuel de la taxe foncière indiqué sur votre avis d'imposition. Varie selon la commune et la surface (en moyenne 15-25€/m² par an).")

provision_copro = st.number_input("Provisions sur charges de copropriété annuelles (€)", value=1000)
st.caption("💡 Montant annuel des charges de copropriété. En moyenne 20-50€/m²/an selon les services (ascenseur, gardien, etc.).")

assurances = st.number_input("Primes d'assurances annuelles (GLI, PNO…) (€)", value=500)
st.caption("💡 Montant annuel total : PNO (propriétaire non occupant) 150-300€/an + GLI (garantie loyers impayés, optionnelle) 2-4% des loyers annuels.")

st.subheader("🏦 Prêt immobilier")
capital = st.number_input("Montant du prêt (€)", value=200000)
st.caption("💡 Montant emprunté (généralement 80-90% du prix d'achat + frais de notaire).")

taux_annuel = st.number_input("Taux annuel (%)", value=2.0)
st.caption("💡 Taux d'intérêt nominal annuel du prêt (en 2024-2025 : généralement entre 3,5% et 4,5% sur 20-25 ans).")

duree_annees = st.number_input("Durée du prêt (années)", value=20)
st.caption("💡 Durée d'emprunt typique : 15, 20 ou 25 ans.")

assurance_emprunteur = st.number_input("Assurance emprunteur annuelle (€)", value=600)
st.caption("💡 Montant annuel de l'assurance de prêt. En moyenne 0,25-0,40% du capital emprunté par an (ex : 500-800€/an pour 200 000€).")

interets_emprunt, mensualite = calcul_interets_annuels(capital, taux_annuel, duree_annees)
st.write(f"💡 Intérêts réels estimés sur la première année : {interets_emprunt:.2f} €")
st.write(f"💡 Mensualité estimée du prêt : {mensualite:.2f} € / mois")

charges_classiques = taxe_fonciere + provision_copro + assurances
results = []

def generate_pdf(df, RFR, parts, loyers, type_bien, prix_bien, valeur_terrain=0):
    # Créer le PDF en mémoire
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    story = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=10
    )
    
    # Titre
    story.append(Paragraph("Rapport de simulation fiscale immobilière", title_style))
    story.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y')}", styles["Normal"]))
    story.append(Spacer(1, 20))
    
    # Paramètres de la simulation
    story.append(Paragraph("Paramètres de la simulation", heading_style))
    params_data = [
        ["Revenu Fiscal de Référence", f"{RFR:,.2f} €"],
        ["Nombre de parts fiscales", f"{parts}"],
        ["Revenus locatifs annuels", f"{loyers:,.2f} €"],
        ["Type de bien", type_bien],
        ["Prix d'achat", f"{prix_bien:,.2f} €"],
    ]
    if type_bien == "Maison individuelle":
        params_data.append(["Valeur du terrain", f"{valeur_terrain:,.2f} €"])
        
    t = Table(params_data, colWidths=[4*inch, 2*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    
    # Résultats par régime
    story.append(Paragraph("Résultats par régime", heading_style))
    results_data = [["Régime", "Surcoût fiscal induit", "Rendement net", "Revenu net"]]
    for _, row in df.iterrows():
        results_data.append([
            row["Type"],
            f"{row['Surcoût fiscal (€)']:,.2f} €",
            f"{row['Rendement net (%)']:.2f}%",
            f"{row['Revenu net (€)']:,.2f} €"
        ])
        
    t = Table(results_data, colWidths=[2.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(t)
    
    # Générer le PDF
    doc.build(story)
    return pdf_buffer

if st.button("✨ Lancer la simulation", key="btn_simulation"):
    # Initialiser la session state si nécessaire
    if 'simulation_results' not in st.session_state:
        st.session_state.simulation_results = None
    
    impots_base, _ = impot_progressif(RFR, parts)

    # Liste pour stocker les résultats
    results = []
    
    for type_loc in ["Nue", "Meublée"]:
        for regime in ["Micro", "Reel"]:
            # Vérification plafond micro
            micro_inapplicable = False
            if regime == "Micro":
                if type_loc == "Nue" and loyers > 15000:
                    micro_inapplicable = True
                    regime_name = "micro-foncier"
                elif type_loc == "Meublée" and loyers > 77700:
                    micro_inapplicable = True
                    regime_name = "micro-BIC"
                else:
                    regime_name = "micro-foncier" if type_loc=="Nue" else "micro-BIC"
            else:
                regime_name = regime

            # Calcul de l'amortissement (uniquement pour meublé réel)
            amort_a_appliquer = 0
            if type_loc == "Meublée" and regime == "Reel":
                amort_a_appliquer = amortissement_total

            res = calcul_revenu_foncier(
                loyers, charges_classiques, interets_emprunt, assurance_emprunteur, 
                type_loc, regime, amort_a_appliquer
            )

            if micro_inapplicable:
                # --- Encadré vert sapin/doré pour régime inapplicable ---
                with st.container():
                    st.markdown(f"""
                        <div style='background-color:#1f6f4a; border:2px solid #d4af37; border-radius:10px; padding:15px; margin-bottom:15px;'>
                            <h3>{type_loc} - {regime_name}</h3>
                            <p>⚠️ Ce régime n'est pas applicable car le revenu locatif annuel dépasse le plafond autorisé.</p>
                        </div>
                    """, unsafe_allow_html=True)
                continue

            # Calcul de l'impact fiscal
            revenu_total = RFR - res["deficit_global"] + res["revenu_imposable"]
            total_impot, details = impot_progressif(revenu_total, parts)
            
            # Calcul des prélèvements sociaux
            if type_loc == "Meublée" and regime == "Reel":
                # Pour le LMNP au réel, les PS sont calculés sur le revenu avant amortissement
                assiette_ps = res["revenu_avant_amortissement"]
            else:
                # Pour les autres cas, sur le revenu imposable
                assiette_ps = res["revenu_imposable"]
            
            prelev_sociaux = max(0, assiette_ps) * 0.172  # On applique les PS uniquement sur les revenus positifs
            impot_total_avec_prelev = total_impot + prelev_sociaux
            surcout_fiscal = impot_total_avec_prelev - impots_base
            
            # Calcul du rendement net-net
            cout_total_acquisition = prix_bien + frais_notaire
            charges_totales = charges_classiques + interets_emprunt + assurance_emprunteur
            revenu_net_apres_charges = loyers - charges_totales
            revenu_net_apres_impot = revenu_net_apres_charges - surcout_fiscal
            rendement_net = (revenu_net_apres_impot / cout_total_acquisition) * 100 if cout_total_acquisition else 0
            
            # Calcul du cash-flow
            mensualites_annuelles = mensualite * 12
            charges_annuelles = charges_classiques + mensualites_annuelles
            impact_fiscal_mensuel = surcout_fiscal / 12  # On lisse l'impact fiscal sur l'année
            cash_flow_annuel = loyers - charges_annuelles - surcout_fiscal
            cash_flow_mensuel = cash_flow_annuel / 12

            # Stockage pour diagrammes
            results.append({
                "Type": f"{type_loc} - {regime_name}",
                "Surcoût fiscal (€)": surcout_fiscal,
                "Rendement net (%)": rendement_net,
                "Revenu net (€)": revenu_net_apres_impot
            })

            # --- Bloc encadré vert sapin/doré ---
            with st.container():
                st.markdown(f"""
                    <div style='background-color:#1f6f4a; border:2px solid #d4af37; border-radius:10px; padding:15px; margin-bottom:15px;'>
                        <h3>{type_loc} - {regime_name}</h3>
                        <p><b>Revenu locatif imposable :</b> {res['revenu_imposable']:.2f} €</p>
                        <p><b>Impôt total + PS :</b> {impot_total_avec_prelev:.2f} €</p>
                        <p><b>Surcoût fiscal induit par l'investissement :</b> {surcout_fiscal:.2f} €</p>
                        <p><b>Rendement net-net :</b> {rendement_net:.2f} % ({revenu_net_apres_impot:.2f} €/an)</p>
                        <p><b>Cash-flow :</b> {cash_flow_annuel:.2f} €/an ({cash_flow_mensuel:.2f} €/mois)</p>
                        <p><b>Impact fiscal mensuel :</b> {impact_fiscal_mensuel:.2f} €/mois</p>
                    </div>
                """, unsafe_allow_html=True)
                


                with st.expander("Voir le détail des calculs"):
                    st.write(f"- Revenu locatif brut : {res['revenu_brut']:.2f} €")
                    if res["abattement_pct"] > 0:
                        st.write(f"- Abattement {res['abattement_pct']}% : {res['revenu_brut']*res['abattement_pct']/100:.2f} €")
                    
                    # Afficher les charges seulement pour les régimes réels
                    if regime == "Reel":
                        st.write(f"- Intérêts d'emprunt : {res['interets']:.2f} €")
                        st.write(f"- Assurance emprunteur : {res['assurance_pret']:.2f} €")
                        st.write(f"- Revenu après intérêts : {res['revenu_apres_interets']:.2f} €")
                        st.write(f"- Charges classiques : {res['charges_classiques']:.2f} €")
                    
                    # Afficher "revenu avant amortissement" uniquement pour meublé réel
                    if type_loc == "Meublée" and regime == "Reel":
                        st.write(f"- Revenu avant amortissement : {res['revenu_avant_amortissement']:.2f} €")
                        st.write(f"- Amortissement total calculé : {res['amortissement_total']:.2f} €")
                        st.write(f"- **Amortissement déductible (Art. 39 C) : {res['amortissement_deductible']:.2f} €**")
                        if res['amortissement_non_deductible'] > 0:
                            st.write(f"- Amortissement non déductible cette année : {res['amortissement_non_deductible']:.2f} €")
                            st.warning("⚠️ Ce calcul est simplifié pour vous donner une première estimation. La fiscalité du LMNP est complexe et nécessite l'accompagnement d'un expert-comptable pour une optimisation précise (décomposition par composants, stratégie pluriannuelle, etc.).")
                            st.info("L'amortissement non déduit est reportable sans limite de durée sur les bénéfices futurs (Art. 39 C du CGI)")
                    
                    st.write(f"- **Assiette imposable : {res['revenu_imposable']:.2f} €**")
                    
                    if res['deficit_global']>0:
                        st.write(f"- Déficit foncier imputable : {res['deficit_global']:.2f} €")
                        st.info("Le déficit foncier (hors intérêts) est plafonné à 10 700 € par an")
                    if res['deficit_interets']>0:
                        st.write(f"- Déficit provenant des intérêts : {res['deficit_interets']:.2f} €")
                        st.info("Ce déficit est reportable sur les revenus fonciers des 10 années suivantes")
                    
                    # Détail du calcul de l'impôt par tranches
                    st.write("\n**Détail du calcul de l'impôt par tranches :**")
                    for (bas, haut, taux), detail in zip(bareme, details):
                        tranche_imposable, impot_tranche = detail[3], detail[4]
                        if tranche_imposable > 0:
                            haut_str = f"{haut:,.0f}" if haut != float('inf') else "∞"
                            st.write(f"Tranche {bas:,.0f}-{haut_str} € à {taux*100:.0f}% : {tranche_imposable:.2f} € imposable => {impot_tranche:.2f} € impôt")

                    st.write(f"\n- Revenu global pour impôt : {revenu_total:.2f} €")
                    st.write(f"- Prélèvements sociaux (17,2%) : {prelev_sociaux:.2f} €")

    # --- Diagramme 1 : Surcoût fiscal ---
    df = pd.DataFrame(results)
    st.markdown("## 💰 Surcoût fiscal induit par l'investissement immobilier")
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(df["Type"], df["Surcoût fiscal (€)"], color=["#1f6f4a", "#3c9b70", "#b69329", "#d4af37"])
    ax.set_ylabel("Montant (€)")
    ax.set_title("Surcoût fiscal induit par l'investissement selon le régime")
    plt.xticks(rotation=45, ha='right')
    ax.bar_label(bars, fmt="%.0f €", label_type="center", color="white", fontweight="bold", fontsize=10)
    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)

    # --- Diagramme 2 : Rendement net après impôts ---
    st.markdown("## 📊 Rendement net après impôts")
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(df["Type"], df["Rendement net (%)"], color=["#1f6f4a", "#3c9b70", "#b69329", "#d4af37"])
    ax.set_ylabel("Rendement net (%)")
    ax.set_title("Rendement net après impôts (%)")
    plt.xticks(rotation=45, ha='right')
    ax.bar_label(bars, labels=[f"{v:.0f} €" for v in df["Revenu net (€)"]], label_type="center",
                 color="white", fontweight="bold", fontsize=10)
    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)

    # Sauvegarder les résultats dans la session state
    st.session_state.simulation_results = {
        'df': df,
        'RFR': RFR,
        'parts': parts,
        'loyers': loyers,
        'type_bien': type_bien,
        'prix_bien': prix_bien,
        'valeur_terrain': valeur_terrain
    }

# Bouton pour générer le PDF (en dehors du if st.button de la simulation)
if st.session_state.get('simulation_results') is not None:
    if st.button("📄 Générer le rapport PDF", key="btn_generate_pdf"):
        # Récupérer les données de la session
        sim_results = st.session_state.simulation_results
        
        # Générer le PDF
        pdf_buffer = generate_pdf(
            sim_results['df'],
            sim_results['RFR'],
            sim_results['parts'],
            sim_results['loyers'],
            sim_results['type_bien'],
            sim_results['prix_bien'],
            sim_results['valeur_terrain']
        )
        
        # Offrir le téléchargement
        st.download_button(
            label="📥 Télécharger le rapport PDF",
            data=pdf_buffer.getvalue(),
            file_name=f"simulation_fiscale_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mime="application/pdf",
            key="btn_download_pdf"
        )