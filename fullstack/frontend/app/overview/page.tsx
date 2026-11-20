import OverviewContent from '../overview-content';

export default function OverviewPage() {
  return <main className="overview-document">
    <nav aria-label="Summary navigation">
      <a className="button secondary" href="/">Systems Lab home</a>
      <a className="button text-button" href="#walkthrough">Jump to walkthrough</a>
    </nav>
    <OverviewContent/>
  </main>;
}
