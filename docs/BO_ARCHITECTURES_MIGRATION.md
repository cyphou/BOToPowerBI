# Architectures de migration SAP BusinessObjects

> **Lecture rapide :** ces schémas sont des options d’architecture, pas une
> migration exécutée. Chaque cible reste soumise aux validations de données,
> sécurité, fraîcheur, coûts et acceptation métier.

Ce guide aide à choisir une cible pour les rapports et univers BO, puis à
organiser leur migration vers Power BI et, si nécessaire, Fabric. Les schémas
décrivent des **architectures cibles** : ils ne signifient pas que le dépôt
exécute toutes les opérations représentées.

## 1. Point de départ : BO n'est pas la source de toutes les données

```mermaid
flowchart LR
    DB["Sources opérationnelles et analytiques<br/>SQL, fichiers, SAP, BW..."]
    U["Univers UNX / UNV<br/>objets, jointures, contextes"]
    R["WebI / Crystal / Lumira<br/>requêtes, calculs, visuels"]
    E["Extraction locale BO<br/>15 collections intermédiaires"]
    G["Génération locale"]
    DB --> U --> R
    U --> E
    R --> E
    E --> G
    G --> P["PBIP : modèle sémantique + rapport"]
    G --> F["Définitions Fabric : Lakehouse,<br/>ingestion, notebook, modèle, pipeline"]
    DB -. "connexion ou ingestion à concevoir" .-> P
    DB -. "connexion ou ingestion à concevoir" .-> F
```

L'univers décrit notamment une couche métier et des accès aux données ; un
rapport décrit aussi des requêtes, calculs et présentations. Les artefacts
extraits ne constituent pas une copie complète, historique et validée des
données des systèmes sous-jacents. Inventorier séparément sources, propriétaires,
droits d'accès, volumétries, historiques, fréquence, traitements et consommateurs.
Une connexion directe à BW peut être transitoire, mais ne permet pas à elle seule
de retirer BW. Pour ce chantier distinct, voir le
[design BW vers Fabric](SAP_BW_TO_FABRIC_DESIGN.md).

## 2. Choisir la cible

| Situation | Cible à examiner | Arbitrages |
|---|---|---|
| Un rapport autonome, source conservée et accessible | PBIP avec modèle sémantique propre au rapport | Simple pour un pilote ; duplication possible des définitions et des rafraîchissements |
| Plusieurs rapports avec données et définitions métier compatibles | Modèle sémantique partagé et rapports légers | Mutualisation ; gouvernance des mesures, compatibilité des sources et gestion des changements indispensables |
| Données à réutiliser, historiser ou transformer au-delà des rapports | Lakehouse Fabric, puis modèle sémantique et rapports | Ingestion et exploitation supplémentaires ; sécurité, coûts, historique et alimentation durable à concevoir |

Ce ne sont pas des cibles mutuellement exclusives : un modèle partagé peut
consommer des tables Lakehouse. Le choix dépend notamment des sources réelles,
des contraintes de fraîcheur, du volume, des licences, de la sécurité et des
consommateurs. Le mode **Import**, **DirectQuery** ou **Direct Lake** doit être
choisi et testé pour chaque architecture ; un univers BO ne détermine pas ce
mode à lui seul.

## 3. Parcours A : modèle sémantique par rapport

```mermaid
flowchart LR
    B["Rapport BO + univers associé"] --> X["Extraction et conversion locales"]
    X --> M["Modèle sémantique TMDL<br/>tables, relations, mesures, rôles à revoir"]
    X --> P["Rapport Power BI PBIR"]
    S["Sources de données existantes"] --> M
    M --> P
    P --> V["Validation Desktop, données,<br/>sécurité et utilisateurs"]
```

1. Recenser le document, son univers, les requêtes et sources effectives.
2. Évaluer le rapport, puis générer un PBIP local. Examiner séparément
   l'univers et vérifier la couverture des métadonnées nécessaires.
3. Vérifier les tables, granularités, jointures, formules, filtres, prompts,
   visuels et règles de sécurité. Revoir les conversions signalées et les
   fonctionnalités qui exigent une reconstruction manuelle.
4. Configurer les connexions et, si nécessaire, la passerelle dans
   l'environnement autorisé. Ouvrir le PBIP et comparer les résultats à BO.

Exemple local : placer les rapports à migrer dans un nouveau dossier `sources` :

```powershell
python migrate.py "examples\Enterprise_Sales.wid" --assess
python migrate.py "sources" --output-dir "artifacts\bo-report"
python migrate.py --validate-project "artifacts\bo-report" --quality-output "artifacts\bo-report-quality.json"
```

L'option `--universe` apparaît dans l'aide du CLI mais n'est actuellement pas
raccordée au parcours de génération d'un rapport unique : ne pas considérer
qu'elle ajoute automatiquement les métadonnées de l'univers au rapport. Une
extraction d'univers séparée ne garantit pas non plus leur fusion dans ce
parcours. La validation locale ne remplace ni l'ouverture Desktop, ni le
rafraîchissement, ni la comparaison métier.

## 4. Parcours B : modèle sémantique partagé

```mermaid
flowchart LR
    R1["Rapport BO A"] --> E["Extractions séparées"]
    R2["Rapport BO B"] --> E
    U["Univers et sources compatibles"] --> E
    E --> C["Évaluation et rapprochement<br/>des tables et définitions"]
    C --> M["Modèle sémantique partagé"]
    C --> P1["Rapport léger A"]
    C --> P2["Rapport léger B"]
    S["Sources conservées ou tables Lakehouse"] --> M
    M --> P1
    M --> P2
```

1. Grouper les rapports par domaine, sources **physiques**, granularité et
   définitions métier, pas uniquement par nom d'univers.
2. Évaluer le rapprochement et faire résoudre les ambiguïtés par les
   propriétaires. Une table isolée est conservée ; cela ne crée pas une relation.
3. Générer le modèle et les rapports, puis contrôler les mesures communes et
   spécifiques, relations, sécurité et impacts d'un changement partagé.
4. Comparer chaque rapport source à son équivalent cible et valider les usages.

```powershell
python migrate.py --shared-model "examples\eFashion_Universe.unx" "examples\HR_Universe.unx" --assess-merge
```

Cet exemple d'univers indépendants présente un faible recouvrement. Le
[guide avancé](MIGRATION_REFERENCE.md#-shared-semantic-model-mode) documente la génération avec
approbation explicite `--force-merge` : celle-ci ne résout pas une ambiguïté
entre sources physiques distinctes. Ne jamais forcer un rapprochement sans
revue. Le chemin partagé ne publie pas les artefacts via `--deploy` ; prévoir
une publication séparée et autorisée.

## 5. Parcours C : Lakehouse Fabric puis modèle sémantique

```mermaid
flowchart LR
    SRC["Sources sous-jacentes<br/>bases, fichiers, SAP, BW..."] --> I["Ingestion choisie par source<br/>et alimentation durable"]
    I --> B["Bronze<br/>données brutes + traçabilité"]
    B --> S["Silver<br/>qualité et transformations"]
    S --> G["Gold<br/>tables métier / faits et dimensions"]
    BO["Univers et rapports BO"] --> META["Extraction des métadonnées<br/>et règles métier"]
    META -. "concevoir et valider" .-> S
    META -. "concevoir et valider" .-> G
    META -. "génération et revue" .-> M
    G --> M["Modèle sémantique<br/>Direct Lake ou autre mode adapté"]
    M --> R["Rapports Power BI"]
    O["Orchestration, supervision,<br/>sécurité et gouvernance"] -.-> I
    O -.-> S
    O -.-> G
```

**Architecture de référence, non générée intégralement par le dépôt.** Bronze,
Silver et Gold peuvent être des schémas d'un Lakehouse compatible ou des
Lakehouses/workspaces séparés selon les exigences d'isolation. Concevoir
historiques, reprise, chargements incrémentaux, suppressions, contrats de
données, conservation et qualité selon les garanties de chaque source.
Un watermark seul ne prouve pas la capture des suppressions.

Pour le mode Fabric actuel, `--output-format fabric` produit **localement** des
définitions Lakehouse/DDL, Dataflow Gen2, notebook PySpark, modèle Direct Lake
et pipeline. Il ne génère pas automatiquement une architecture complète en
trois couches ni une alimentation historique ou incrémentale fiable de toutes
les sources. CSV/Excel sont affectés au notebook ; sources connectées et SQL
personnalisé au Dataflow ; les colonnes calculées sont matérialisées dans le
notebook principal après ingestion. Inspecter le plan d'ingestion, de
matérialisation et les constats de qualité avant de poursuivre.

### SQL WebI/Universe et cible RDL

Le SQL incorporé dans une requête WebI peut être repris en Power Query avec
`Value.NativeQuery` dans une partition du modèle ou dirigé vers un Dataflow
Gen2. Les partitions M générées ne reçoivent plus d'enveloppe automatique
`try ... otherwise` : les erreurs de source ne sont pas volontairement masquées
par un résultat de remplacement. Une expression fournie explicitement peut
conserver son propre traitement d'erreur. L'adaptateur rattache la
requête à une source lorsqu'une référence explicite par nom ou identifiant
(`id`) se résout de façon unique, ou lorsqu'une seule source est disponible.
Les requêtes sans référence en contexte multi-source, ou avec une référence
absente, ambiguë ou non résolue, sont signalées par l'adaptateur et restent
non rattachées. Dataflow rejette explicitement ces requêtes ; il ne substitue
pas de connexion fictive (`localhost`/`MyDB`). Le SQL extrait d'une table
dérivée d'univers peut également alimenter une requête native, mais les objets,
transformations et définitions métier de l'univers ne prouvent pas que le SQL
complet exécuté pour le rapport a été extrait. Vérifier ce SQL et sa provenance
dans les artefacts source.

#### RDL SQL explicite — génération locale et contrôles statiques

La génération SQL est implémentée à partir d'un mapping JSON local sans
identifiants d'authentification. Son contrat contient exactement `title`,
`source_kind` (`webi`, `crystal`, `lumira`, `desktop_intelligence`, `xcelsius`,
`analysis_olap` ou `universe`), `server`, `database`, `sql` et `columns`.
Ce libellé est une déclaration, pas la preuve que le format a été extrait ni
que sa sémantique ou sa mise en page a été convertie. Pour les formats sans
extraction locale du SQL, la requête, ses champs et sa connexion restent à
fournir manuellement. La sélection directe de fichier reste limitée à WebI,
Crystal et aux univers ; voir la matrice des limites dans le README.
Le générateur émet un RDL avec une source SQL Server (`Data Source` et
`Initial Catalog`), un dataset utilisant le SQL fourni et un tablix construit
avec les colonnes déclarées. Ces noms de colonnes ne sont pas comparés au
résultat réel de la requête. Une colonne SQL peut associer explicitement un
nom technique `field` à un libellé de tableau `label` ; le rapprochement avec
un objet métier BO reste manuel. Le mapping ne contient aucun secret ; les
identifiants d'accès sont à configurer séparément dans l'environnement
d'exécution. Les caractères Unicode et la ponctuation pris en charge dans les
noms du serveur et de la base sont conservés tels quels ; les points-virgules,
accolades et caractères de contrôle sont refusés pour protéger la chaîne de
connexion.

Des contrôles statiques bornés exigent une instruction de forme `SELECT`,
refusent `SELECT INTO`, les instructions multiples ou séparées par un point-
virgule interne, les paramètres SQL nommés non liés tels que `@Region` (aucun
`QueryParameters` RDL n'est déclaré), ainsi que les macros BO `@Prompt` et
`@Variable`. Les paramètres SQL, prompts et variables BO sont non pris en
charge et ne sont pas convertis. Un point-virgule terminal est toléré. Ce
contrôle de forme n'est ni un parseur SQL complet ni une preuve de validité, de
sûreté ou d'exécution sur SQL Server.

Il est aussi possible de sélectionner par son nom exact une entrée unique
de `custom_sql.json`, préalablement produit par l'extracteur local WebI,
Crystal ou univers, avec `--rdl-extracted-sql` et `--rdl-sql-name` (voir le README).
On peut aussi fournir directement un fichier local `.wid`, `.rpt`, `.unx` ou `.unv`
avec `--rdl-bo-source` et sélectionner le SQL par son nom exact, sans écrire
de JSON intermédiaire. Le type du fichier doit correspondre à `source_kind`.
Pour un univers, seul le SQL d'une table dérivée est repris, pas celui d'un
rapport reconstruit. Les formats binaires et la couverture complète de
l'extraction ne sont pas garantis. Pour Crystal, l'extraction `.rpt` repère
des chaînes ressemblant à des requêtes dans le texte lisible du binaire ;
`CommandSQL` est un nom synthétique, et l'extraction ne confirme ni l'objet
Command ni l'intégralité de la requête.
Un dossier peut être traité avec `--output-format rdl --rdl-batch-config` et
un mapping explicite par fichier (contrat et exemple dans le README). Les
archives BIAR ne sont pas converties vers RDL par ce parcours ; leur échec est
signalé par fichier et les autres sources continuent.
Le mapping doit alors déclarer les champs réellement renvoyés et la connexion
SQL Server, mais omettre `sql`. L'extraction est partielle : le SQL sélectionné,
son origine et son rattachement au rapport doivent être vérifiés manuellement.
Protéger les fichiers extraits et le RDL, qui peuvent contenir du SQL sensible.

Avec ce même mapping SQL Server, `--rdl-power-query-output fichier.m` génère
en plus du RDL une expression M locale utilisant la même connexion et le même
SQL. Les deux fichiers doivent être nouveaux ; un échec d'écriture peut laisser
un fichier partiel. Les champs et libellés du RDL ne filtrent ni ne renomment
les colonnes de la requête M. Aucun identifiant d'authentification n'est ajouté.
La requête native doit être relue avant exécution avec des permissions adaptées :
les contrôles de forme ne prouvent pas son innocuité. Les macros BO et les
paramètres SQL non liés restent refusés dans ce parcours.

#### Choisir Desktop ou Desktop optimisé pour Report Server

- **Desktop classique** : générer le PBIP, l'ouvrir et le valider, puis
  éventuellement l'enregistrer en PBIX depuis Desktop. La génération locale ne
  prouve pas l'ouverture ni la fidélité.
- **Desktop pour Report Server** : le format PBIP n'y est pas pris en charge.
  Créer une requête vide, coller le fichier `.m` dans l'éditeur avancé,
  configurer la connexion puis reconstruire manuellement le modèle et les
  visuels, avant d'enregistrer un PBIX avec l'édition RS adaptée au serveur.
  La compatibilité des fonctionnalités et de la version doit être vérifiée.
- **Rapport paginé** : le RDL se modifie dans Microsoft Report Builder ou SSDT
  et se publie séparément ; ce n'est pas un PBIX Desktop.

Microsoft décrit les limites [PBIP](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview),
l'[édition Desktop pour Report Server](https://learn.microsoft.com/en-us/power-bi/report-server/install-powerbi-desktop)
et le [parcours RDL](https://learn.microsoft.com/en-us/power-bi/report-server/quickstart-create-paginated-report).
Le dépôt ne fournit pas de conversion PBIP vers PBIX vérifiée. Ouverture Desktop,
rafraîchissement, rendu Report Builder et publication restent `not_run`.

Les archives BIAR/LCMBIAR ne sont reconnues que pour les artefacts directement
identifiables par leur extension dans le ZIP. Si aucun n'est reconnu, le CLI
échoue sans créer de sortie vide : un contenu segmenté ou encapsulé reste
inconnu, et cela ne prouve pas que l'archive ne contient aucun rapport BO.

Il s'agit d'un tableau de résultats, pas d'une conversion du rapport BO :
aucun onglet, visuel ou objet métier n'est automatiquement associé au tableau.
Les paramètres/prompts, formules, filtres, mise en page et permissions BO ne
sont pas convertis. Les contrôles statiques ne testent ni l'exécution de la
requête ni l'ouverture ou le rendu dans Report Builder ; ces vérifications
restent `not_run`.

L'option RDL existante DAX → modèle sémantique reste distincte : son mapping
fournit la requête DAX et les champs attendus. L'option `--universe` du CLI
n'est pas raccordée à la génération d'un rapport et ne remplit aucun des deux
mappings automatiquement.

```powershell
python migrate.py "examples\Enterprise_Sales.wid" --assess
python migrate.py "sources" --output-format fabric --output-dir "artifacts\bo-fabric"
python migrate.py --validate-project "artifacts\bo-fabric" --quality-output "artifacts\bo-fabric-quality.json"
```

La génération Fabric échoue avec le code **6** en présence de constats locaux
bloquants et conserve les rapports de qualité pour diagnostic ; les
avertissements seuls ne bloquent pas. Utiliser `--quality-strict` lors de la
validation pour traiter aussi les avertissements comme bloquants. Les
connexions, identités et liaisons manquantes doivent être résolues dans
l'environnement cible après autorisation.
Sur l'exemple synthétique `Enterprise_Sales`, la génération locale est
actuellement bloquée par des calculs/groupes BO nécessitant une reprise
manuelle : l'exemple illustre le diagnostic, pas un déploiement prêt à l'emploi.

Pour Direct Lake, vérifier les tables Delta, les types, les relations et le
rafraîchissement/framing. Les tables Direct Lake générées utilisent des
partitions d'entité et une expression OneLake partagée ; certaines tables
utilitaires peuvent rester en Import et sont signalées. Les enrichissements
automatiques de calendrier et de dates en Import ne sont pas équivalents à une
matérialisation amont en Direct Lake. Direct Lake sur OneLake ne propose pas de
repli DirectQuery ; Direct Lake sur point de terminaison SQL peut en proposer
selon la configuration et le scénario. Tester le mode effectivement déployé,
ses permissions et sa performance, sans supposer que les deux variantes sont
interchangeables.

## 6. Traduction des concepts : propositions à valider

| Objet ou comportement BO | Cible possible | Point de contrôle |
|---|---|---|
| Univers, classes et objets métier | Tables, colonnes, mesures et dossiers d'un modèle sémantique | Périmètre, définitions partagées et droits |
| Jointures et contextes d'univers | Relations, vues ou transformations en amont | Cardinalité, chemins de filtre, pièges de jointure et granularité |
| Objets de type mesure et variables | Mesures DAX ou calculs en amont | Contexte d'évaluation, agrégations, arrondis et valeurs nulles |
| Tables dérivées et SQL personnalisé | Requête source, Dataflow ou transformation Lakehouse | Compatibilité SQL, performances et accès à la source |
| Prompts, filtres, contrôles et listes de valeurs | Paramètres, segments ou filtres | Valeurs obligatoires, défauts, dépendances et expérience utilisateur |
| Onglets, graphiques et alerteurs | Pages, visuels et mise en forme conditionnelle | Rendu, navigation, interaction et fonctionnalités non converties |
| Profils de sécurité et restrictions | Rôles du modèle, droits Fabric et contrôles sur les données | Tests d'accès autorisé **et refusé**, y compris accès direct aux données |
| Planifications et instances BO | Rafraîchissement, orchestration et distribution à définir | Fuseaux, fréquence, destinataires, échecs et historique |

Ces correspondances ne sont pas des équivalences automatiques. Notamment,
reproduire une sécurité RLS au niveau du modèle ne protège pas nécessairement
les autres chemins d'accès au Lakehouse. Valider chaque chemin et identité.

## 7. Livraison et critères de passage

1. **Inventaire et choix** : dépendances, sources, consommateurs, criticité,
   sécurité, données et cible approuvées par les responsables.
2. **Pilote** : choisir un domaine représentatif ; consigner les écarts,
   conversions manuelles et décisions de modélisation.
3. **Génération locale** : examiner les fichiers produits et le rapport de
   qualité ; corriger ou accepter explicitement les avertissements applicables.
4. **Validation fonctionnelle** : comparer BO et cible avec des jeux
   indépendants, les mêmes filtres et granularités, et des seuils métier
   approuvés ; vérifier totaux, détails, contextes, nulls et cas limites.
5. **Validation technique et sécurité** : ouverture Desktop, actualisation,
   données et performances ; tester les permissions à chaque couche et les
   chemins d'accès directs. Pour Lakehouse, tester ingestion, reprise et
   réconciliation de chaque couche.
6. **Publication et bascule** : après autorisation distincte, lier et publier,
   superviser, exécuter une période parallèle, documenter le retour arrière et
   obtenir l'acceptation métier avant retrait du contenu BO.

Une génération réussie ou un contrôle statique ne prouve pas l'exécution Fabric,
la restitution dans Desktop, l'équivalence métier ni l'autorisation de retrait.
Consigner séparément les contrôles réellement exécutés et ceux restés `not_run`.
Les définitions extraites peuvent contenir des informations de connexion
sensibles : protéger les sorties et les examiner avant partage.

## Références

- [Architecture interne du projet](ARCHITECTURE.md) et
  [guide de migration entreprise](ENTERPRISE_GUIDE.md).
- [Configuration Fabric et MCP](FABRIC_MCP_SETUP.md) et
  [routage des skills Fabric](../.github/skills/fabric-mcp-routing/SKILL.md).
- Microsoft Learn : [fonctionnement de Direct Lake](https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-how-it-works)
  et [développement des modèles Direct Lake](https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-develop).
