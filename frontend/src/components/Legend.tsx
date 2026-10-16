import { LOAD_RULES, RISK_BANDS, RISK_COLORS, RISK_LABELS, THRESHOLD_TABLE } from "../lib/risk";

/** The brief's risk table, shown so a colour on the map can be read back
 * to the threshold that produced it without leaving the page. */
export function Legend() {
  return (
    <details className="legend">
      <summary>
        <span className="legend__swatches" aria-hidden="true">
          {RISK_BANDS.map((level) => (
            <span key={level} style={{ background: RISK_COLORS[level] }} />
          ))}
        </span>
        Risk thresholds
      </summary>

      <table className="legend__table">
        <thead>
          <tr>
            <th scope="col">Condition</th>
            {RISK_BANDS.map((level) => (
              <th key={level} scope="col">
                <span className="legend__dot" style={{ background: RISK_COLORS[level] }} />
                {RISK_LABELS[level]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {THRESHOLD_TABLE.map((row) => (
            <tr key={row.condition}>
              <th scope="row">
                {row.condition} <span className="legend__unit">{row.unit}</span>
              </th>
              {row.bands.map((band) => (
                <td key={band}>{band}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <h4>Load rules</h4>
      <ul className="legend__rules">
        {LOAD_RULES.map((rule) => (
          <li key={rule}>{rule}</li>
        ))}
      </ul>
    </details>
  );
}
